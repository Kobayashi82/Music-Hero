"""generate canción.mp3 | carpeta/ -> chart.json + vista previa HTML (+ carpeta para YARG/Clone Hero).

Uso:
    uv run --project generator generate "D:/Musica/Artista - Canción.mp3"
    uv run --project generator generate "D:/Musica/Artista"            # toda la carpeta (y subcarpetas)
    uv run --project generator generate carpeta/ --jobs 2              # dos canciones a la vez
    uv run --project generator generate carpeta/ --max-minutes 30      # sin las de más de 30 min
    uv run --project generator generate canción.mp3 --clonehero      # también notes.chart + song.ini
    uv run --project generator generate canción.mp3 --human chart.sng # chart hecha por personas, sincronizada

Por defecto usa el modelo models/best.pt (las 4 dificultades); --no-model, las reglas (solo Experto).
Si la canción tiene chart humana bajada (data/encore_library.json -> out/encore/), usa esa y el modelo
solo para las dificultades que falten, o para todo si no encaja con el audio; --no-human lo desactiva.
Caché: si out/<canción>/chart.json ya es de ese mismo audio (hash) y de esta versión del generador
y del modelo, la canción se salta; --force la rehace. Los stems de Demucs se guardan para no repetirlo
(~50 MB por canción); --drop-stems los borra al terminar.
También hace la letra sincronizada (lyrics.json, ver generator/lyrics.py), y la añade a las charts ya
hechas que no la tengan; --no-lyrics la desactiva.
"""

import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from . import __version__

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = ROOT / "out" / "charts"
DEFAULT_MODEL = ROOT / "models" / "best.pt"
AUDIO_EXT = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".wma"}
# Canciones de la biblioteca con chart humana en Chorus Encore (tools/encore_dataset.py library) y
# dónde están bajadas. Se usan solas salvo con --no-human.
LIBRARY_JSON = ROOT / "data" / "encore_library.json"
LIBRARY_SNG = ROOT / "out" / "encore"
# La chart humana no encaja con el audio (otra versión, o la búsqueda emparejó otra canción) y se usa el
# modelo si se afinan menos del 40 % de las anclas, o menos del 60 % con un desfase que varía más de 20 s
# (en las 129 de la biblioteca: remixes, covers y versiones de otra duración; las buenas dan 75-98 %).
MIN_HUMAN_CONFIDENCE = 0.4
DOUBTFUL_HUMAN = (0.6, 20.0)  # (confianza, rango del desfase en s)


def find_audio(paths: list[str]) -> list[Path]:
    """Archivos de audio de la lista; las carpetas se recorren enteras. Una ruta vacía, que no existe
    o que no es audio es un error (una vacía sería la carpeta actual: recorrería todo el proyecto)."""
    out = []
    for raw in paths:
        if not str(raw).strip():
            raise ValueError("ruta vacía")
        p = Path(raw)
        if not p.exists():
            raise ValueError(f"no existe: {p}")
        if p.is_file() and p.suffix.lower() not in AUDIO_EXT:
            raise ValueError(f"no es un archivo de audio: {p}")
        if p.is_dir():
            out += sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in AUDIO_EXT)
        else:
            out.append(p)
    return out


def too_long(files: list[Path], max_minutes: float) -> list[Path]:
    """Las que duran más de max_minutes (lee solo la cabecera)."""
    import soundfile as sf

    out = []
    for f in files:
        try:
            if sf.info(str(f)).duration > max_minutes * 60:
                out.append(f)
        except Exception:  # noqa: BLE001 - si no se puede leer, que lo diga generate
            pass
    return out


def library_human(audio: Path) -> Path | None:
    """Chart humana bajada para este archivo de la biblioteca, si la hay."""
    try:
        found = json.loads(LIBRARY_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    key = str(audio.resolve()).lower()
    for m in found:
        if str(Path(m["file"])).lower() == key:
            for p in (LIBRARY_SNG / f"{m['md5']}.sng", LIBRARY_SNG / m["md5"]):
                if p.exists():
                    return p
    return None


def generator_version(model_path: Path | None, human_chart: Path | None, max_nps: dict[str, float] | None = None) -> str:
    """Versión que se guarda en chart.json: cambia si cambia el algoritmo, el modelo, la chart humana
    o los límites de densidad."""
    from .audio import sha256_file

    v = __version__
    if human_chart is not None:
        v += f"+humana-{sha256_file(human_chart)[:8]}" if human_chart.is_file() else f"+humana-{human_chart.name}"
    if model_path is not None:  # con chart humana, rellena las dificultades que falten (o la sustituye si no encaja)
        v += f"+{model_path.stem}-{sha256_file(model_path)[:8]}"
        if max_nps:
            v += "+nps-" + "-".join(f"{k}{n:g}" for k, n in sorted(max_nps.items()))
    return v


def _chart_of(out: Path) -> dict | None:
    try:
        return json.loads((out / "chart.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def out_dir_for(audio: Path, sha: str, out_root: Path) -> Path:
    """out/<nombre>; si ahí ya hay la chart de otro audio con el mismo nombre, out/<nombre> (<hash>)."""
    name = audio.stem.rstrip(" .") or "sin nombre"  # Windows quita el punto o espacio final de las carpetas
    out = out_root / name
    old = _chart_of(out)
    if old is not None and old.get("song", {}).get("audio_sha256") not in (None, sha):
        out = out_root / f"{name} ({sha[:8]})"
    return out


def plan_out_dirs(files: list[Path], out_root: Path) -> dict[Path, Path]:
    """Carpeta de cada canción del lote, decidida antes de repartirlas entre procesos: dos audios
    distintos con el mismo nombre (p. ej. en dos discos) procesados a la vez elegirían la misma."""
    from .audio import sha256_file

    plan, taken = {}, {}  # carpeta -> hash
    for f in files:
        sha = sha256_file(f)
        out = out_dir_for(f, sha, out_root)
        if taken.get(out, sha) != sha:
            out = out.with_name(f"{out.name} ({sha[:8]})")
        taken[out] = sha
        plan[f] = out
    return plan


def up_to_date(out: Path, sha: str, version: str, clonehero: bool = False) -> bool:
    c = _chart_of(out)
    return (c is not None and c.get("song", {}).get("audio_sha256") == sha
            and c.get("generator", {}).get("version") == version
            and (out / "preview.html").exists() and (not clonehero or (out / "clonehero").exists()))


def generate(audio: Path, out_root: Path, clonehero: bool = False, device: str = "cuda",
             human_chart: Path | None = None, model_path: Path | None = None, force: bool = False,
             max_nps: dict[str, float] | None = None, drop_stems: bool = False, tag: str = "",
             out_dir: Path | None = None, use_library: bool = True, lyrics: bool = True) -> Path | None:
    """Genera la chart de una canción. Devuelve su carpeta, o None si ya estaba hecha (caché).
    use_library: sin human_chart, usar la chart humana de la biblioteca si está bajada.
    lyrics: hacer también lyrics.json (generator.lyrics), también si la chart ya estaba y le falta."""
    from .audio import song_info

    t0 = time.perf_counter()

    def step(msg: str) -> None:
        print(f"{tag}  [{time.perf_counter() - t0:5.1f} s] {msg}", flush=True)

    if human_chart is None and use_library:
        human_chart = library_human(audio)
    song = song_info(audio)
    version = generator_version(model_path, human_chart, max_nps)
    out = out_dir or out_dir_for(audio, song.audio_sha256, out_root)
    if not force and up_to_date(out, song.audio_sha256, version, clonehero):
        print(f"{tag}{audio.name}: ya hecha ({out.name})", flush=True)
        if lyrics:
            _lyrics(out, device, drop_stems, step)
        return None
    print(f"{tag}{song.artist} - {song.title}  ({song.duration_ms / 1000:.0f} s)", flush=True)

    from .export_chart import chart_json, write_clonehero, write_json
    from .feel import analyze
    from .mapping import MapParams, map_expert
    from .model import MELODIC_STEMS
    from .preview import write_preview
    from .rhythm import TempoMap, detect_beats, steady_beats
    from .separate import separate
    from .transcribe import transcribe

    out.mkdir(parents=True, exist_ok=True)
    stems = separate(audio, out / "stems", device)
    step("pistas separadas (Demucs htdemucs_6s)")

    beats, downbeats = detect_beats(audio, device)
    if len(set(beats)) < 4:
        beats, downbeats = steady_beats(song.duration_ms)
        step("sin pulsos claros: rejilla fija de 120 BPM")
    tempo = TempoMap.from_beats(beats, downbeats)
    step(f"{len(beats)} pulsos, {len(downbeats)} compases, ~{tempo.bpm_at(len(beats) / 2):.0f} BPM, "
         f"{tempo.beats_per_measure}/4")

    trans = {s: transcribe(stems[s], s) for s in MELODIC_STEMS}
    step("notas: " + ", ".join(f"{s} {len(t.notes)}" for s, t in trans.items()))

    feel = analyze(audio, stems["drums"])
    end_beat = tempo.ms_to_beat(song.duration_ms)
    params = MapParams()
    if max_nps:
        params.max_nps.update(max_nps)
    notes, sections, source = map_expert(trans, tempo, end_beat, params, feel=feel)
    energy = sum(s.energy for s in sections) / max(1, len(sections))
    step(f"chart Experto: {len(notes)} notas, energía media {energy:.2f}")
    difficulties = {"expert": notes}

    if model_path is not None:
        from .learn.infer import predict
        from .mapping import map_from_model

        difficulties = map_from_model(trans, tempo, sections, predict(audio, model_path, device), params)
        notes = difficulties["expert"]
        step(f"modelo {model_path.name}: " + ", ".join(f"{d} {len(n)}" for d, n in difficulties.items()))

    if human_chart is not None:
        from . import human

        hc = human.load(human_chart)
        alignment = human.align(hc.audio_files, audio)
        offs = alignment.offsets()
        sync = (f"{hc.name} ({hc.charter}), anclas afinadas {alignment.confidence:.0%}, "
                f"desfase {offs.min() / 1000:+.2f}..{offs.max() / 1000:+.2f} s")
        doubtful = alignment.confidence < DOUBTFUL_HUMAN[0] and (offs.max() - offs.min()) / 1000 > DOUBTFUL_HUMAN[1]
        if (alignment.confidence < MIN_HUMAN_CONFIDENCE or doubtful) and len(difficulties) == 4:
            step(f"chart humana descartada, no encaja con el audio: {sync}")
        else:
            shifted = {d: n for d, n in human.shift(hc.difficulties, alignment, tempo).items() if n}
            filled = [d for d in difficulties if d not in shifted]
            difficulties = {d: shifted.get(d) or difficulties[d] for d in ("expert", "hard", "medium", "easy")
                            if d in shifted or d in difficulties}
            step(f"chart humana: {sync}: " + ", ".join(f"{d} {len(n)}" for d, n in shifted.items())
                 + (f"; del modelo: {', '.join(filled)}" if filled else ""))
            notes = difficulties.get("expert", notes)

    data = chart_json(song, tempo, difficulties, sections, version)
    write_json(out / "chart.json", data)
    write_preview(out / "preview.html", song, tempo, notes, sections, source, version, difficulties)
    if clonehero:
        write_clonehero(out / "clonehero", song, tempo, difficulties, sections)
    if lyrics:
        _lyrics(out, device, False, step)
    if drop_stems:
        shutil.rmtree(out / "stems", ignore_errors=True)
    step(f"listo: {out}")
    return out


def _lyrics(out: Path, device: str, drop_stems: bool, step) -> None:
    """lyrics.json de la chart (si falta o es de otra versión). Un fallo no estropea la chart, solo se avisa."""
    from .lyrics import lyrics_for

    try:
        d = lyrics_for(out, device)
    except Exception as e:  # noqa: BLE001 - p. ej. LRCLIB caído: se hará en otra pasada
        step(f"letra: error {type(e).__name__}: {e}")
        return
    if d is not None:
        step(f"letra: {d['source']}, {len(d['lines'])} líneas")
        if drop_stems:  # los stems se habían vuelto a separar solo para la letra
            shutil.rmtree(out / "stems", ignore_errors=True)


def _worker(kw: dict) -> tuple[str, str, float]:
    """Una canción en un proceso aparte: (archivo, 'hecha' | 'saltada' | 'error: ...', segundos)."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    t0 = time.perf_counter()
    try:
        r = generate(**kw)
        status = "saltada" if r is None else "hecha"
    except Exception as e:  # noqa: BLE001 - una canción rara no para el lote
        status = f"error: {type(e).__name__}: {e}"
    return str(kw["audio"]), status, time.perf_counter() - t0


def parse_max_nps(text: str) -> dict[str, float]:
    """'expert=14,easy=3' -> {'expert': 14.0, 'easy': 3.0}"""
    out = {}
    for part in filter(None, (p.strip() for p in text.split(","))):
        k, v = part.split("=")
        if k not in ("expert", "hard", "medium", "easy"):
            raise ValueError(f"dificultad desconocida: {k}")
        out[k] = float(v)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", nargs="+", help="canciones o carpetas")
    parser.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT, help=f"carpeta de salida (por defecto {DEFAULT_OUT})")
    parser.add_argument("--clonehero", action="store_true", help="exporta también notes.chart + song.ini + audio")
    parser.add_argument("--cpu", action="store_true", help="sin GPU")
    parser.add_argument("--human", type=Path, help="chart hecha por personas (.sng o carpeta) para sincronizar y usar")
    parser.add_argument("--no-human", action="store_true",
                        help=f"no usar las charts humanas de la biblioteca ({LIBRARY_JSON.name}, bajadas en out/encore/)")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL,
                        help=f"modelo entrenado para las 4 dificultades (por defecto {DEFAULT_MODEL.name})")
    parser.add_argument("--no-model", action="store_true", help="sin modelo: reglas, solo Experto")
    parser.add_argument("--force", action="store_true", help="rehacer aunque ya esté hecha")
    parser.add_argument("--jobs", type=int, default=1, help="canciones a la vez (cada una en un proceso; 2 va bien en 12 GB)")
    parser.add_argument("--max-nps", type=parse_max_nps, default={},
                        help="notas/s como mucho en 2 s, p. ej. 'expert=14,hard=8,medium=5,easy=3.5'")
    parser.add_argument("--max-minutes", type=float, help="saltar las canciones que duren más de esto")
    parser.add_argument("--drop-stems", action="store_true", help="borrar los stems al terminar cada canción")
    parser.add_argument("--no-lyrics", action="store_true", help="sin letra sincronizada (lyrics.json)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    model = None if args.no_model else args.model
    if model is not None and not model.exists():
        if args.model != DEFAULT_MODEL:
            parser.error(f"no existe el modelo {model}")
        print(f"aviso: no hay {DEFAULT_MODEL}; se usan las reglas (solo Experto)")
        model = None
    try:
        files = find_audio(args.audio)
    except ValueError as e:
        parser.error(str(e))
    if args.max_minutes:
        long_ = set(too_long(files, args.max_minutes))
        if long_:
            print(f"se saltan {len(long_)} de más de {args.max_minutes:g} min: " + ", ".join(f.name for f in sorted(long_)))
        files = [f for f in files if f not in long_]
    if not files:
        parser.error("no hay archivos de audio")
    common = dict(out_root=args.out, clonehero=args.clonehero, device="cpu" if args.cpu else "cuda",
                  human_chart=args.human, model_path=model, force=args.force, max_nps=args.max_nps,
                  drop_stems=args.drop_stems, use_library=not args.no_human, lyrics=not args.no_lyrics)
    if len(files) == 1:
        generate(files[0], **common)
        return 0

    print(f"{len(files)} canciones, {args.jobs} a la vez, modelo: {model.name if model else 'ninguno (reglas)'}")
    t0, results = time.perf_counter(), []
    plan = plan_out_dirs(files, args.out)
    jobs = [dict(common, audio=f, out_dir=plan[f], tag=f"[{i + 1}/{len(files)}] ") for i, f in enumerate(files)]
    if args.jobs <= 1:
        results = [_worker(kw) for kw in jobs]
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for fut in as_completed([pool.submit(_worker, kw) for kw in jobs]):
                results.append(fut.result())
    done = sum(s == "hecha" for _, s, _ in results)
    skipped = sum(s == "saltada" for _, s, _ in results)
    errors = [(f, s) for f, s, _ in results if s.startswith("error")]
    print(f"\nFin en {(time.perf_counter() - t0) / 60:.1f} min: {done} hechas, {skipped} ya estaban, {len(errors)} con error")
    for f, s in errors:
        print(f"  {Path(f).name}: {s}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
