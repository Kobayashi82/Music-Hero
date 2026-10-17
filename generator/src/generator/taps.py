"""Ritmo marcado a mano con la grabadora (app: `tap`) -> eventos de la chart.

Los toques dicen CUÁNDO y CUÁNTO dura cada nota (lo que se siente); la
transcripción solo pone la altura, para elegir el botón por contorno.

El usuario oye la canción con retardo (audio, reflejos), así que los toques
llegan tarde respecto a la posición de AIMP. El desfase se estima comparando los
toques con los ataques fuertes del audio y se resta.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from .rhythm import TempoMap, quantize

if TYPE_CHECKING:
    from .feel import Feel
    from .mapping import Event
    from .transcribe import Transcription

ROOT = Path(__file__).resolve().parents[3]
TAPS_DIR = ROOT / "data" / "taps"
# Retardo con el que llegan los toques (salida de audio + reflejos), medido en este equipo con
# las canciones de acentos claros: Give Up ~210 ms, Queen ~260, Apocalypse ~300.
DEFAULT_OFFSET_MS = 260
OFFSET_RANGE_MS = (-100, 500)
OFFSET_TOL_MS = 40
MIN_OFFSET_SCORE = 0.4  # por debajo, los acentos no explican los toques (canción suave)


@dataclass
class Taps:
    path: Path
    taps: list[tuple[int, int]]  # (inicio, fin) en ms, tal cual se grabaron
    covered: list[tuple[int, int]]  # tramos escuchados al grabar
    offset_ms: int = 0  # retardo estimado (se resta)

    def covers(self, ms: float) -> bool:
        return any(a <= ms <= b for a, b in self.covered)


def load(audio: Path, sha256: str) -> Taps | None:
    path = TAPS_DIR / f"{audio.stem}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("audio_sha256") not in (None, sha256):
        print(f"  aviso: {path.name} se grabó con otro archivo de audio; se ignora")
        return None
    taps = [(int(a), int(b)) for a, b in data.get("taps", [])]
    if not taps:
        return None
    covered = [(int(a), int(b)) for a, b in data.get("covered", [])] or [(taps[0][0] - 1000, taps[-1][1] + 1000)]
    return Taps(path, taps, covered)


def accent_peaks(feel: Feel, min_accent: float = 0.4) -> np.ndarray:
    a = feel.mix_accent
    is_peak = (a[1:-1] > a[:-2]) & (a[1:-1] >= a[2:]) & (a[1:-1] >= min_accent)
    return feel.times_ms[1:-1][is_peak]


def strong_accents(feel: Feel, covered: list[tuple[int, int]], n: int) -> np.ndarray:
    """Los n máximos de acento más fuertes dentro de los tramos escuchados."""
    a, t = feel.mix_accent, feel.times_ms
    i = np.where((a[1:-1] > a[:-2]) & (a[1:-1] >= a[2:]))[0] + 1
    i = i[np.array([any(x <= t[k] <= y for x, y in covered) for k in i], bool)]
    return np.sort(t[i[np.argsort(-a[i])[:n]]])


def estimate_offset(tap_starts: list[int], peaks_ms: np.ndarray) -> tuple[int, float]:
    """Desfase global (toque - audio) que pone más toques sobre un acento, y la fracción que lo
    hace. Se barre un rango amplio: emparejar cada toque con el ataque más cercano falla en cuanto
    el retardo pasa de medio intervalo entre acentos (Give Up y Queen daban ~0 con 200-300 ms reales)."""
    taps = np.asarray(tap_starts, float)
    peaks = np.sort(np.asarray(peaks_ms, float))
    if len(taps) < 8 or len(peaks) < 2:
        return 0, 0.0

    def signed(off: float) -> np.ndarray:
        x = taps - off
        i = np.clip(np.searchsorted(peaks, x), 1, len(peaks) - 1)
        a, b = x - peaks[i - 1], x - peaks[i]
        return np.where(abs(a) <= abs(b), a, b)

    offs = np.arange(OFFSET_RANGE_MS[0], OFFSET_RANGE_MS[1] + 1, 5)
    scores = [float((abs(signed(o)) <= OFFSET_TOL_MS).mean()) for o in offs]
    k = int(np.argmax(scores))
    d = signed(offs[k])
    return int(round(offs[k] + np.median(d[abs(d) <= OFFSET_TOL_MS]))), scores[k]


def fit_offset(taps: Taps, feel: Feel) -> bool:
    """Pone taps.offset_ms; False si los acentos no lo aclaran y se usa el retardo por defecto."""
    starts = [a for a, _ in taps.taps]
    off, score = estimate_offset(starts, strong_accents(feel, taps.covered, 2 * len(starts)))
    taps.offset_ms = off if score >= MIN_OFFSET_SCORE else DEFAULT_OFFSET_MS
    return score >= MIN_OFFSET_SCORE


def tap_events(taps: Taps, trans: dict[str, Transcription], section_stem_at, tempo: TempoMap) -> list[Event]:
    """Un evento por toque. Altura: la voz si canta justo ahí; si no, la pista del tramo."""
    from .mapping import Event

    events: dict[float, Event] = {}
    last_pitch = 52
    for start, end in taps.taps:
        s, e = start - taps.offset_ms, end - taps.offset_ms
        beat = round(quantize(tempo.ms_to_beat(s)), 6)
        end_beat = tempo.ms_to_beat(e)
        pitches = _pitches_at(s, trans.get("vocals"), 120) or _pitches_at(s, trans.get(section_stem_at(s) or "guitar"), 150)
        if not pitches:
            pitches = {last_pitch: 0.5}
        last_pitch = min(pitches)
        ev = Event(beat, end_beat, pitches, "taps", strong=True)
        ev.salience = 1.0
        if beat not in events or end_beat > events[beat].end_beat:
            events[beat] = ev
    return sorted(events.values(), key=lambda e: e.beat)


def _pitches_at(t: float, trans: Transcription | None, window_ms: int) -> dict[int, float]:
    if trans is None:
        return {}
    near = [n for n in trans.notes if abs(n.start_ms - t) <= window_ms and n.amp >= 0.3]
    if not near:
        near = [n for n in trans.notes if n.start_ms <= t < n.end_ms and n.amp >= 0.3]
    if not near:
        return {}
    best_start = min(near, key=lambda n: abs(n.start_ms - t)).start_ms
    return {n.pitch: n.amp for n in near if abs(n.start_ms - best_start) <= 40}
