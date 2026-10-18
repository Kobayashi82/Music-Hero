"""Letra sincronizada palabra a palabra -> lyrics.json junto a la chart (shared/lyrics_schema.json).

    uv run --project generator lyrics                         (todas las charts de out/charts)
    uv run --project generator lyrics "<canción.mp3 | carpeta de música | carpeta de chart>" [--force]

De dónde sale, por orden:
1. LRCLIB (https://lrclib.net, gratis y sin clave): el texto, por artista, título, álbum y duración. Sus
   tiempos no se usan: a menudo son de otra versión de la canción (en Complicated iban 7,5 s tarde).
2. stable-ts (Whisper) ajusta ese texto a la pista de voz separada (stems/vocals.flac): tiempo de cada
   palabra. Comprobado contra la transcripción libre de Whisper.
3. Sin letra en LRCLIB: transcripción de Whisper sobre la voz, quitando los trozos de poca confianza y las
   frases fantasma típicas. Con voces susurradas se equivoca más: queda marcada como source "whisper".
Las canciones sin letra (instrumentales, o sin nada fiable) también se apuntan, para no repetirlas.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LYRICS_VERSION = "2"
SCHEMA_VERSION = 1
WHISPER_MODEL = "large-v3-turbo"
LRCLIB = "https://lrclib.net/api"
USER_AGENT = "MusicHero/0.1 (https://github.com/Kobayashi82/Music-Hero)"
DURATION_TOLERANCE_S = 6
MIN_WHISPER_PROB = 0.55  # confianza media mínima de un trozo transcrito
MIN_WORDS = 20  # menos que esto (transcrito) no se considera letra
MIN_MISMATCH_CONF = 0.5  # texto de LRCLIB con otra duración: por debajo, el ajuste directo no vale
MIN_MERGE_MATCH = 0.5  # parte del texto de LRCLIB que debe aparecer en la transcripción para usarlo
HALLUCINATIONS = re.compile(r"(thank you|thanks for watching|subtitles?|subtítulos|gracias por ver|amara\.org|"
                            r"ご視聴|字幕|おやすみなさい|♪)", re.I)
DEFAULT_CHARTS = Path(__file__).resolve().parents[3] / "out" / "charts"


# ---------- LRCLIB ----------

def _get(url: str, tries: int = 6) -> object:
    """GET a LRCLIB; reintenta los 5xx y los cortes (da 503 a ratos). Si no hay forma, la excepción sube."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code < 500 and e.code != 429 or attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
        time.sleep(min(2 ** attempt, 20))


def _clean_title(title: str) -> str:
    """'Gosia (Mokum Sessions)' -> 'Gosia'; 'Song - Remastered 2011' -> 'Song'."""
    t = re.sub(r"\s*[\(\[].*?[\)\]]\s*", " ", title)
    return re.sub(r"\s+-\s+.*(remaster|version|live|edit|mix).*$", "", t, flags=re.I).strip() or title


def _norm(s: str) -> str:
    return re.sub(r"\W+", "", s.casefold())


def fetch_lrclib(title: str, artist: str, album: str, duration_s: float) -> dict | None:
    """El registro de LRCLIB que mejor encaja, o None. Primero con duración parecida; si no hay, uno del mismo
    artista y título aunque dure otra cosa (otra edición, con intro...): de él solo vale el texto, y si no encaja
    con la voz, make_lyrics lo descarta por la confianza. Ese caso lleva "duration_mismatch"."""
    q = {"track_name": title, "artist_name": artist, "album_name": album, "duration": round(duration_s)}
    hit = _get(f"{LRCLIB}/get?{urllib.parse.urlencode(q)}")
    if isinstance(hit, dict) and (hit.get("plainLyrics") or hit.get("instrumental")):
        return hit
    same: list[dict] = []
    for name in dict.fromkeys([title, _clean_title(title)]):
        found = _get(f"{LRCLIB}/search?{urllib.parse.urlencode({'track_name': name, 'artist_name': artist})}") or []
        found = [h for h in found if h.get("plainLyrics") or h.get("instrumental")]
        good = [h for h in found if abs((h.get("duration") or 0) - duration_s) <= DURATION_TOLERANCE_S]
        if good:
            return min(good, key=lambda h: (not h.get("plainLyrics"), abs(h["duration"] - duration_s)))
        same += [h for h in found if h.get("plainLyrics") and _norm(h.get("artistName", "")) == _norm(artist)
                 and _norm(_clean_title(h.get("trackName", ""))) == _norm(_clean_title(title))]
        time.sleep(0.2)
    if same:
        return min(same, key=lambda h: abs((h.get("duration") or 0) - duration_s)) | {"duration_mismatch": True}
    return None


def lyric_lines(text: str) -> list[str]:
    """Texto plano -> líneas cantadas (sin vacías ni etiquetas tipo [Chorus])."""
    out = []
    for line in text.splitlines():
        line = re.sub(r"^\s*[\[\(](verse|chorus|bridge|intro|outro|pre-chorus|hook|coro|estribillo)[^\]\)]*[\]\)]\s*$",
                      "", line, flags=re.I).strip()
        if re.search(r"\w", line):  # fuera las vacías y las de solo símbolos ("♪")
            out.append(line)
    return out


# ---------- Whisper (stable-ts) ----------

_model = None


def load_model(device: str = "cuda"):
    global _model
    if _model is None:
        import stable_whisper

        _model = stable_whisper.load_model(WHISPER_MODEL, device=device)
    return _model


def detect_language(model, vocals: Path) -> str:
    """Idioma de los 30 s con más voz."""
    import numpy as np
    import whisper

    audio = whisper.load_audio(str(vocals))
    sr, win = whisper.audio.SAMPLE_RATE, 30 * whisper.audio.SAMPLE_RATE
    if len(audio) > win:
        secs = len(audio) // sr  # energía por segundo (sumar bloques; una convolución aquí tarda minutos)
        energy = (audio[:secs * sr].reshape(secs, sr) ** 2).sum(axis=1)
        start = int(np.argmax(np.convolve(energy, np.ones(30), "valid"))) * sr
        audio = audio[start:start + win]
    mel = whisper.log_mel_spectrogram(whisper.pad_or_trim(audio), n_mels=model.dims.n_mels).to(model.device)
    _, probs = model.detect_language(mel)
    return max(probs, key=probs.get)


MIN_WORD_MS = 60  # palabras más cortas: tiempo roto de Whisper (a menudo varias en el mismo instante)
SPREAD_WORD_MS = 220  # lo que se les da como mucho a cada una al repartirlas
MAX_LINE_MS = 7000  # líneas más largas se parten, para que quepan bajo la autopista
MAX_LINE_WIDTH = 46  # ancho en caracteres latinos (uno japonés o chino cuenta dos)
_PUNCT = tuple("、。，,.!?！？;；:")


def _width(text: str) -> int:
    return sum(2 if ord(c) >= 0x2E80 else 1 for c in text)


def _fix_short_words(words: list[dict]) -> None:
    """Rachas de palabras sin duración (todas las de la canción, en orden): se reparten hasta la siguiente; si
    esa empieza justo ahí, se comparte también la duración de esa."""
    def short(w: dict) -> bool:
        return w["end_ms"] - w["start_ms"] < MIN_WORD_MS

    i = 0
    while i < len(words):
        if not short(words[i]):
            i += 1
            continue
        j = i
        while j < len(words) and short(words[j]):
            j += 1
        start = words[i]["start_ms"]
        stop = words[j]["start_ms"] if j < len(words) else start + SPREAD_WORD_MS * (j - i)
        if stop - start < MIN_WORD_MS * (j - i) and j < len(words):
            stop, j = words[j]["end_ms"], j + 1
        stop = min(stop, start + SPREAD_WORD_MS * (j - i))
        step = (stop - start) / (j - i)
        if step > 0:
            for k in range(i, j):
                words[k]["start_ms"] = round(start + step * (k - i))
                words[k]["end_ms"] = round(start + step * (k - i + 1))
        i = j


def _kind(c: str) -> str:
    if "぀" <= c <= "ゟ":
        return "hira"
    if "゠" <= c <= "ヿ":
        return "kata"
    return "kanji" if "一" <= c <= "鿿" else "other"


def _cjk_cut(before: str, after: str) -> int:
    """Qué tal es partir una línea japonesa entre estas dos palabras (sin diccionario: por el tipo de letra)."""
    before, after = before.rstrip(), after.lstrip()
    if not before or not after:
        return 0
    a, b = before[-1], after[0]
    if b in "ーゃゅょっぁぃぅぇぉャュョッァィゥェォ" or _kind(a) == _kind(b) == "kata":
        return -800  # a mitad de una palabra en katakana o de una sílaba
    if _kind(a) == "kanji" and _kind(b) == "hira":
        return -400  # entre el kanji y su terminación
    if _kind(a) == "hira" and _kind(b) in ("kanji", "kata"):
        return 300  # tras una partícula o terminación, antes de palabra nueva
    return 0


def _make_line(words: list[dict]) -> dict:
    return {"start_ms": words[0]["start_ms"], "end_ms": words[-1]["end_ms"],
            "text": "".join(w["text"] for w in words).strip(), "words": words}


def split_line(words: list[dict]) -> list[dict]:
    """Una línea demasiado larga (en tiempo o en ancho) -> varias, partiendo por la mejor pausa."""
    text = "".join(w["text"] for w in words)
    if len(words) < 4 or (words[-1]["start_ms"] - words[0]["start_ms"] <= MAX_LINE_MS  # la última puede alargarse
                          and _width(text.strip()) <= MAX_LINE_WIDTH):
        return [_make_line(words)]
    total, acc, best, best_score = _width(text), 0, 1, float("-inf")
    for i in range(1, len(words)):
        acc += _width(words[i - 1]["text"])
        if i < 2 or i > len(words) - 2:
            continue
        gap = words[i]["start_ms"] - words[i - 1]["end_ms"]
        score = (min(gap, 1500) + 400 * words[i - 1]["text"].rstrip().endswith(_PUNCT)
                 + 250 * words[i]["text"].startswith(" ") * (_width(text) > len(text))  # espacio en japonés
                 + _cjk_cut(words[i - 1]["text"], words[i]["text"])
                 - 1500 * abs(acc / total - 0.5))
        if score > best_score:
            best, best_score = i, score
    return split_line(words[:best]) + split_line(words[best:])


def _lines_of(result, min_prob: float = 0.0) -> tuple[list[dict], float]:
    """Resultado de stable-ts -> líneas del lyrics.json y confianza media de las palabras."""
    segs, conf = _segs_of(result, min_prob)
    return _finish_lines(segs), conf


def _segs_of(result, min_prob: float = 0.0) -> tuple[list[list[dict]], float]:
    """Resultado de stable-ts -> palabras por línea y confianza media de las palabras.
    min_prob > 0 = transcripción libre: se quitan trozos dudosos, fantasmas y líneas con el tiempo roto."""
    segs, probs, last = [], [], ""
    for seg in result.segments:
        ws = [w for w in seg.words if w.word.strip()]
        if not ws:
            continue
        p = sum(w.probability for w in ws) / len(ws)
        text = "".join(w.word for w in ws).strip()
        if min_prob:
            if p < min_prob or HALLUCINATIONS.search(text):
                continue
            if text.casefold() == last and len(ws) <= 3:
                continue  # bucle típico de Whisper repitiendo lo mismo
            if (ws[-1].end - ws[0].start) * 1000 < MIN_WORD_MS * len(ws):
                continue  # todas las palabras en el mismo instante: tiempo inventado
        last = text.casefold()
        probs += [w.probability for w in ws]
        segs.append([{"start_ms": round(w.start * 1000), "end_ms": round(w.end * 1000), "text": w.word} for w in ws])
    return segs, (sum(probs) / len(probs) if probs else 0.0)


def _finish_lines(segs: list[list[dict]]) -> list[dict]:
    """Palabras por línea -> líneas del lyrics.json: tiempos rotos arreglados, sin líneas amontonadas en un
    instante (no se podrían leer) y partidas si son demasiado largas."""
    words = [w for ws in segs for w in ws]
    _fix_short_words(words)
    for w, nxt in zip(words, words[1:]):  # ninguna acaba después de que empiece la siguiente
        w["end_ms"] = max(min(w["end_ms"], nxt["start_ms"]), w["start_ms"])
    return [line for ws in segs for line in split_line(ws)
            if line["end_ms"] - line["start_ms"] >= 40 * len(line["words"])]


def _tokens(line: str) -> list[str]:
    """Palabras de una línea; en japonés o chino (sin espacios), cada carácter con la puntuación que le sigue."""
    if _width(line) > len(line):
        return re.findall(r"\W*(?:[A-Za-z0-9']+|\w)\W*", line)
    return re.findall(r"\s*\S+", line)


def _keep_main_cluster(hit: dict, li: int, n: int, gap_ms: int = 2500) -> None:
    """Las letras de una línea emparejadas lejos (en tiempo) del grueso de la línea son casualidades: fuera."""
    times = sorted((s, ti) for ti in range(n) for s, _ in hit.get((li, ti), []))
    if not times:
        return
    groups, cur = [], [times[0]]
    for prev, t in zip(times, times[1:]):
        if t[0] - prev[0] > gap_ms:
            groups.append(cur)
            cur = []
        cur.append(t)
    groups.append(cur)
    main = max(groups, key=len)
    lo, hi = main[0][0], main[-1][0]
    for ti in range(n):
        if (li, ti) in hit:
            kept = [x for x in hit[li, ti] if lo <= x[0] <= hi]
            if kept:
                hit[li, ti] = kept
            else:
                del hit[li, ti]


def merge_with_transcript(text_lines: list[str], segs: list[list[dict]]) -> tuple[list[list[dict]], float]:
    """Texto bueno (LRCLIB) con los tiempos de la transcripción libre: se emparejan los dos textos letra a letra
    y cada palabra toma el tiempo de las letras transcritas que le tocan. Para cuando el ajuste directo falla
    (versión con otra intro o duración). Devuelve las palabras por línea y la parte del texto emparejada."""
    from difflib import SequenceMatcher

    tchars, ttimes = [], []
    for w in (w for ws in segs for w in ws):
        k = _norm(w["text"])
        for n in range(len(k)):
            span = (w["end_ms"] - w["start_ms"]) / len(k)
            tchars.append(k[n])
            ttimes.append((w["start_ms"] + span * n, w["start_ms"] + span * (n + 1)))
    toks = [[{"text": t} for t in _tokens(line)] for line in text_lines]
    lchars, owner = [], []
    for li, line in enumerate(toks):
        for ti, t in enumerate(line):
            for c in _norm(t["text"]):
                lchars.append(c)
                owner.append((li, ti))
    hit: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for a, b, size in SequenceMatcher(None, tchars, lchars, autojunk=False).get_matching_blocks():
        for n in range(size):
            hit.setdefault(owner[b + n], []).append(ttimes[a + n])
    out = []
    for li, line in enumerate(toks):
        _keep_main_cluster(hit, li, len(line))
        got = sum(len(hit.get((li, ti), [])) for ti in range(len(line)))
        if not line or got < 0.3 * sum(len(_norm(t["text"])) for t in line):
            continue  # línea casi sin emparejar: no se sabe dónde va
        for ti, t in enumerate(line):
            if (li, ti) in hit:
                t["start_ms"] = round(min(s for s, _ in hit[li, ti]))
                t["end_ms"] = round(max(e for _, e in hit[li, ti]))
        ti = 0
        while ti < len(line):  # las que faltan, repartidas entre las vecinas
            if "start_ms" in line[ti]:
                ti += 1
                continue
            end = ti
            while end < len(line) and "start_ms" not in line[end]:
                end += 1
            count = end - ti
            lo = line[ti - 1]["end_ms"] if ti else max(line[end]["start_ms"] - SPREAD_WORD_MS * count, 0)
            hi = line[end]["start_ms"] if end < len(line) else lo + SPREAD_WORD_MS * count
            step = max(hi - lo, 0) / count
            for k in range(ti, end):
                line[k]["start_ms"] = round(lo + step * (k - ti))
                line[k]["end_ms"] = round(lo + step * (k - ti + 1))
            ti = end
        out.append(line)
    matched = sum(len(v) for v in hit.values()) / max(len(lchars), 1)
    return out, matched


def make_lyrics(song: dict, vocals: Path, device: str = "cuda", use_whisper: bool = True) -> dict:
    t0 = time.perf_counter()
    rec = fetch_lrclib(song["title"], song.get("artist", ""), song.get("album", ""), song["duration_ms"] / 1000)
    base = {"schema_version": SCHEMA_VERSION, "audio_sha256": song["audio_sha256"],
            "generator": {"version": LYRICS_VERSION, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "model": WHISPER_MODEL}}
    def done(**kw) -> dict:
        return base | kw | {"seconds": round(time.perf_counter() - t0, 1)}

    if rec and rec.get("instrumental") and not rec.get("duration_mismatch"):
        return done(source="instrumental", lines=[])
    model = load_model(device)
    lang = detect_language(model, vocals)
    text = lyric_lines(rec["plainLyrics"]) if rec and rec.get("plainLyrics") else []
    if text:
        result = model.align(str(vocals), "\n".join(text), language=lang, original_split=True)
        if result is not None:
            out, conf = _lines_of(result)
            if out and (conf >= MIN_MISMATCH_CONF or not rec.get("duration_mismatch")):
                return done(source="lrclib", language=lang, confidence=round(conf, 3), lrclib_id=rec.get("id"),
                            lines=out)
    if not use_whisper:
        return done(source="none", lines=[])
    segs, conf = _segs_of(model.transcribe(str(vocals), language=lang, verbose=None), MIN_WHISPER_PROB)
    if text:  # el ajuste directo no encajó: texto de LRCLIB con los tiempos de la transcripción
        merged, matched = merge_with_transcript(text, segs)
        if matched >= MIN_MERGE_MATCH:
            return done(source="lrclib+whisper", language=lang, confidence=round(conf, 3),
                        matched=round(matched, 3), lrclib_id=rec.get("id"), lines=_finish_lines(merged))
    out = _finish_lines(segs)
    if sum(len(l["words"]) for l in out) < MIN_WORDS:
        return done(source="none", language=lang, lines=[])
    return done(source="whisper", language=lang, confidence=round(conf, 3), lines=out)


def up_to_date(folder: Path, sha: str) -> bool:
    try:
        d = json.loads((folder / "lyrics.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return d.get("audio_sha256") == sha and d.get("generator", {}).get("version") == LYRICS_VERSION


def lyrics_for(folder: Path, device: str = "cuda", force: bool = False, use_whisper: bool = True) -> dict | None:
    """Hace lyrics.json para una carpeta de chart. None si ya estaba hecho."""
    song = json.loads((folder / "chart.json").read_text(encoding="utf-8"))["song"]
    if not force and up_to_date(folder, song["audio_sha256"]):
        return None
    vocals = folder / "stems" / "vocals.flac"
    if not vocals.exists():  # stems borrados (--drop-stems): se vuelve a separar
        from .separate import separate

        vocals = separate(Path(song["audio_file"]), folder / "stems", device)["vocals"]
    data = make_lyrics(song, vocals, device, use_whisper)
    tmp = folder / "lyrics.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(folder / "lyrics.json")
    return data


# ---------- línea de órdenes ----------

def chart_folders(targets: list[Path], charts_dir: Path = DEFAULT_CHARTS) -> list[Path]:
    """Carpetas de chart: las dadas, las que hay dentro, o las de los audios dados (por su ruta)."""
    by_audio: dict[str, Path] | None = None
    out: list[Path] = []
    for t in targets or [charts_dir]:
        if (t / "chart.json").exists():
            out.append(t)
        elif t.is_dir() and any(t.glob("*/chart.json")):
            out += sorted(p.parent for p in t.glob("*/chart.json"))
        else:  # audio o carpeta de música: se busca la chart por la ruta del audio
            if by_audio is None:
                by_audio = {}
                for c in charts_dir.glob("*/chart.json"):
                    try:
                        a = json.loads(c.read_text(encoding="utf-8"))["song"].get("audio_file", "")
                    except (OSError, ValueError, KeyError):
                        continue
                    by_audio[str(Path(a)).casefold()] = c.parent
            key = str(t.resolve()).casefold()
            out += [f for a, f in by_audio.items() if a == key or a.startswith(key.rstrip("\\/") + "\\")]
    return list(dict.fromkeys(out))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("targets", nargs="*", type=Path, help="canciones, carpetas de música o de chart")
    parser.add_argument("--force", action="store_true", help="rehacer aunque ya esté")
    parser.add_argument("--no-whisper", action="store_true", help="solo LRCLIB (sin transcribir las que no tengan)")
    parser.add_argument("--cpu", action="store_true")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    args = parser.parse_args()
    folders = chart_folders(args.targets)
    if not folders:
        print("No encuentro charts para eso.")
        return 1
    device = "cpu" if args.cpu else "cuda"
    t0 = time.perf_counter()
    counts: dict[str, int] = {}
    for i, folder in enumerate(folders, 1):
        try:
            d = lyrics_for(folder, device, args.force, not args.no_whisper)
        except Exception as e:  # noqa: BLE001 - una canción rara no para el lote
            print(f"[{i}/{len(folders)}] {folder.name}: error {type(e).__name__}: {e}", flush=True)
            counts["error"] = counts.get("error", 0) + 1
            continue
        if d is None:
            counts["ya estaba"] = counts.get("ya estaba", 0) + 1
            continue
        counts[d["source"]] = counts.get(d["source"], 0) + 1
        n = sum(len(line["words"]) for line in d["lines"])
        extra = f", confianza {d['confidence']:.2f}" if "confidence" in d else ""
        print(f"[{i}/{len(folders)}] {folder.name}: {d['source']} ({d.get('language', '-')}), "
              f"{len(d['lines'])} líneas, {n} palabras{extra}", flush=True)
    print(f"Fin en {(time.perf_counter() - t0) / 60:.1f} min: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
