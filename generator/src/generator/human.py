"""Charts hechas por personas (Chorus Encore, Rock Band, Clone Hero) sincronizadas con el audio propio.

Lee notes.chart o notes.mid (formato Rock Band: pista "PART GUITAR") de una
carpeta o un .sng, y calcula el desfase entre el audio del paquete y el archivo
del usuario correlando sus curvas de ataque en varios tramos de la canción.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .model import ChartNote

DIFFS = ("expert", "hard", "medium", "easy")
CHART_SECTIONS = {"expert": "ExpertSingle", "hard": "HardSingle", "medium": "MediumSingle", "easy": "EasySingle"}
MID_BASE = {"expert": 96, "hard": 84, "medium": 72, "easy": 60}  # verde; +1..+4 el resto; +5 HOPO forzado; +6 strum forzado
AUDIO_EXT = (".opus", ".ogg", ".mp3", ".wav", ".flac")
STEM_AUDIO = ("song", "guitar", "rhythm", "bass", "drums", "drums_1", "drums_2", "drums_3", "drums_4", "vocals",
              "vocals_1", "vocals_2", "keys", "crowd")


@dataclass
class HumanChart:
    name: str
    charter: str
    difficulties: dict[str, list[ChartNote]]
    audio_files: list[Path]


# ---------- tempo ----------

class _TickMap:
    def __init__(self, resolution: int, tempos: list[tuple[int, float]]):
        """tempos: (tick, microsegundos por pulso)."""
        self.res = resolution
        self.ticks = [0]
        self.us = [tempos[0][1] if tempos and tempos[0][0] == 0 else 500000.0]
        self.ms = [0.0]
        for tick, us in sorted(tempos):
            if tick == 0:
                self.us[0] = us
                continue
            self.ms.append(self.ms[-1] + (tick - self.ticks[-1]) / resolution * self.us[-1] / 1000)
            self.ticks.append(tick)
            self.us.append(us)

    def to_ms(self, tick: int) -> float:
        i = int(np.searchsorted(self.ticks, tick, side="right")) - 1
        return self.ms[i] + (tick - self.ticks[i]) / self.res * self.us[i] / 1000

    def beats(self, tick: int) -> float:
        return tick / self.res


def _finish(raw: list[tuple[int, list[int], int, bool | None]], tm: _TickMap, hopo_ticks: int) -> list[ChartNote]:
    """raw: (tick, botones, duración en ticks, forzado: None / True invierte el HOPO natural)."""
    out: list[ChartNote] = []
    prev = None
    for tick, frets, length, forced in sorted(raw):
        natural = (prev is not None and len(frets) == 1 and tick - prev[0] <= hopo_ticks and frets[0] not in prev[1])
        hopo = natural != bool(forced)
        t = int(round(tm.to_ms(tick)))
        sus = int(round(tm.to_ms(tick + length) - t)) if length >= tm.res * 0.375 else 0
        out.append(ChartNote(t, sorted(frets), sus, hopo, beat=tm.beats(tick), end_beat=tm.beats(tick + length)))
        prev = (tick, frets)
    return out


# ---------- .chart ----------

def read_chart(text: str) -> dict[str, list[ChartNote]]:
    sections = dict(re.findall(r"\[(\w+)\]\s*\{([^}]*)\}", text))
    song = dict(re.findall(r"^\s*(\w+)\s*=\s*\"?([^\"\n]*)\"?\s*$", sections.get("Song", ""), re.M))
    res = int(float(song.get("Resolution", 192)))
    tempos = [(int(t), 60e6 / (int(v) / 1000)) for t, v in re.findall(r"^\s*(\d+)\s*=\s*B\s+(\d+)", sections["SyncTrack"], re.M)]
    tm = _TickMap(res, tempos)
    out = {}
    for diff, name in CHART_SECTIONS.items():
        body = sections.get(name)
        if not body:
            continue
        notes: dict[int, dict] = {}
        for tick, kind, n, length in re.findall(r"^\s*(\d+)\s*=\s*([NS])\s+(\d+)\s+(\d+)", body, re.M):
            if kind != "N":
                continue
            tick, n, length = int(tick), int(n), int(length)
            e = notes.setdefault(tick, {"frets": [], "len": 0, "forced": False})
            if n <= 4:
                e["frets"].append(n)
                e["len"] = max(e["len"], length)
            elif n == 5:
                e["forced"] = True
            elif n == 7:  # nota al aire: la más cercana es el verde
                e["frets"].append(0)
        raw = [(t, sorted(set(e["frets"])), e["len"], e["forced"]) for t, e in notes.items() if e["frets"]]
        out[diff] = _finish(raw, tm, int(round(65 / 192 * res)))
    return out


# ---------- notes.mid (Rock Band) ----------

def read_mid(path_or_bytes: Path | bytes) -> dict[str, list[ChartNote]]:
    import io

    import mido

    if isinstance(path_or_bytes, bytes):
        mid = mido.MidiFile(file=io.BytesIO(path_or_bytes))
    else:
        mid = mido.MidiFile(str(path_or_bytes))
    res = mid.ticks_per_beat
    tempos = []
    for track in mid.tracks[:1]:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                tempos.append((tick, float(msg.tempo)))
    tm = _TickMap(res, tempos)
    guitar = next((t for t in mid.tracks if t.name.strip().upper() in ("PART GUITAR", "T1 GEMS")), None)
    if guitar is None:
        return {}
    events: list[tuple[int, int, bool]] = []  # (tick, nota, encendida)
    tick = 0
    for msg in guitar:
        tick += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            events.append((tick, msg.note, True))
        elif msg.type in ("note_off", "note_on"):
            events.append((tick, msg.note, False))
    out = {}
    for diff, base in MID_BASE.items():
        starts: dict[int, int] = {}
        chords: dict[int, dict] = {}
        forced: list[tuple[int, int, bool]] = []  # (inicio, fin, es_hopo)
        open_forced: dict[int, int] = {}
        for t, note, on in events:
            if base <= note <= base + 4:
                if on:
                    starts[note] = t
                elif note in starts:
                    st = starts.pop(note)
                    e = chords.setdefault(st, {"frets": [], "len": 0})
                    e["frets"].append(note - base)
                    e["len"] = max(e["len"], t - st)
            elif note in (base + 5, base + 6):
                if on:
                    open_forced[note] = t
                elif note in open_forced:
                    forced.append((open_forced.pop(note), t, note == base + 5))
        raw = []
        tm_hopo = int(round(170 / 480 * res))
        prev = None
        for st in sorted(chords):
            e = chords[st]
            frets = sorted(set(e["frets"]))
            natural = prev is not None and len(frets) == 1 and st - prev[0] <= tm_hopo and frets[0] not in prev[1]
            want = natural
            for a, b, is_hopo in forced:
                if a <= st < b:
                    want = is_hopo
            raw.append((st, frets, e["len"], want != natural))
            prev = (st, frets)
        if raw:
            out[diff] = _finish(raw, tm, tm_hopo)
    return out


def load(path: Path) -> HumanChart:
    """Carpeta de chart o .sng."""
    if path.suffix.lower() == ".sng":
        from .sng import read_sng

        meta, files = read_sng(path)
        folder = Path(tempfile.mkdtemp(prefix="music_hero_sng_"))
        for name, data in files.items():
            (folder / name).write_bytes(data)
    else:
        folder = path
    ini = {}
    for f in ("song.ini",):
        if (folder / f).exists():
            ini = dict(re.findall(r"^\s*(\w+)\s*=\s*(.*?)\s*$", (folder / f).read_text(encoding="utf-8", errors="replace"), re.M))
    if path.suffix.lower() == ".sng":
        ini = {**meta, **ini}
    if (folder / "notes.chart").exists():
        diffs = read_chart((folder / "notes.chart").read_text(encoding="utf-8-sig", errors="replace"))
    elif (folder / "notes.mid").exists():
        diffs = read_mid(folder / "notes.mid")
    else:
        raise FileNotFoundError(f"no hay notes.chart ni notes.mid en {folder}")
    # delay del song.ini (ms): el audio va adelantado/retrasado respecto a la chart
    delay = int(float(ini.get("delay", 0) or 0))
    if delay:
        for notes in diffs.values():
            for n in notes:
                n.time_ms += delay
    audio = [p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXT and p.stem.lower() in STEM_AUDIO]
    name = f"{ini.get('artist', '?')} - {ini.get('name', path.stem)}"
    return HumanChart(name, ini.get("charter", ini.get("frets", "?")), diffs, audio)


# ---------- sincronización con el audio propio ----------

SR, HOP = 22050, 220  # curvas de ataque a 100 valores por segundo


@dataclass
class Alignment:
    """Correspondencia tiempo de la chart -> tiempo del audio propio (por tramos)."""

    chart_ms: np.ndarray
    user_ms: np.ndarray
    confidence: float  # fracción de anclas que se pudieron afinar con los ataques

    def __call__(self, t: float) -> float:
        return float(np.interp(t, self.chart_ms, self.user_ms,
                               left=t + self.user_ms[0] - self.chart_ms[0],
                               right=t + self.user_ms[-1] - self.chart_ms[-1]))

    def offsets(self) -> np.ndarray:
        return self.user_ms - self.chart_ms


def _mix(files: list[Path]) -> np.ndarray:
    from .audio import load_mono

    mix = None
    for f in files:
        y = load_mono(f, SR)
        if mix is None:
            mix = y
        else:
            n = max(len(mix), len(y))
            mix = np.pad(mix, (0, n - len(mix))) + np.pad(y, (0, n - len(y)))
    return mix


def align(chart_audio: list[Path], user_audio: Path) -> Alignment:
    """1) DTW sobre croma (armonía, ~10 por segundo): alineación gruesa que admite
    ediciones distintas. 2) Cada 2 s se afina con la correlación de las curvas de
    ataque (±150 ms). 3) Mediana móvil para quitar anclas sueltas erróneas."""
    import librosa

    from .audio import load_mono

    a = _mix(chart_audio)
    b = load_mono(user_audio, SR)
    hop_c = 2048
    ca = librosa.feature.chroma_cqt(y=a, sr=SR, hop_length=hop_c)
    cb = librosa.feature.chroma_cqt(y=b, sr=SR, hop_length=hop_c)
    _, path = librosa.sequence.dtw(X=ca, Y=cb, metric="cosine", subseq=False)
    path = path[::-1]
    coarse_chart = path[:, 0] * hop_c / SR * 1000
    coarse_user = path[:, 1] * hop_c / SR * 1000

    ea = librosa.onset.onset_strength(y=a, sr=SR, hop_length=HOP)
    eb = librosa.onset.onset_strength(y=b, sr=SR, hop_length=HOP)
    ea = (ea - ea.mean()) / (ea.std() + 1e-9)
    eb = (eb - eb.mean()) / (eb.std() + 1e-9)
    fps = SR / HOP

    anchors_c, anchors_u, refined = [], [], 0
    win, search = int(3 * fps), int(0.15 * fps)
    for t in np.arange(3000, len(a) / SR * 1000 - 3000, 2000):
        u = float(np.interp(t, coarse_chart, coarse_user))
        # Velocidad relativa local (versiones a distinta velocidad): pendiente de la alineación gruesa en ±10 s.
        slope = (np.interp(t + 10000, coarse_chart, coarse_user) - np.interp(t - 10000, coarse_chart, coarse_user)) / 20000
        slope = float(np.clip(slope, 0.8, 1.25))
        i = int(t / 1000 * fps)
        x = ea[max(0, i - win):i + win]
        # x estirado a la velocidad del audio propio, centrado en t
        n = int(round(len(x) * slope))
        xs = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x) if len(x) > 1 else x
        j0 = int(round(u / 1000 * fps - (i - max(0, i - win)) * slope)) - search
        y = eb[max(0, j0):j0 + n + 2 * search]
        if len(x) < 2 * win or j0 < 0 or len(y) < n + 2 * search:
            anchors_c.append(t); anchors_u.append(u)
            continue
        c = np.correlate(y, xs, mode="valid")
        k = int(c.argmax())
        peak = (c[k] - np.median(c)) / (c.std() + 1e-9)
        if peak > 2.5:
            u = u + (k - search) / fps * 1000
            refined += 1
        anchors_c.append(t); anchors_u.append(u)

    ac, au = np.array(anchors_c), np.array(anchors_u)
    off = au - ac
    smooth = np.array([np.median(off[max(0, k - 2):k + 3]) for k in range(len(off))])
    return Alignment(ac, ac + smooth, refined / max(1, len(ac)))


def shift(diffs: dict[str, list[ChartNote]], alignment: Alignment, tempo) -> dict[str, list[ChartNote]]:
    """Pasa los tiempos al audio propio y recalcula la posición en pulsos con su mapa de tempo."""
    out = {}
    for d, notes in diffs.items():
        moved = []
        for n in notes:
            t = int(round(alignment(n.time_ms)))
            if t < 0:
                continue
            sus = int(round(alignment(n.time_ms + n.sustain_ms))) - t if n.sustain_ms else 0
            m = ChartNote(t, n.frets, max(0, sus), n.hopo)
            m.beat = tempo.ms_to_beat(t)
            m.end_beat = tempo.ms_to_beat(t + m.sustain_ms) if m.sustain_ms else m.beat
            moved.append(m)
        out[d] = moved
    return out
