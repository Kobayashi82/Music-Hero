"""Pulsos y compases con Beat This!, mapa de tempo y cuantización a la rejilla.

El "eje de pulsos" es continuo: el pulso n es el n-ésimo pulso detectado (más
unos pulsos de entrada antes del primero, para que el pulso 0 caiga en el ms 0).
chart.json y .chart usan el mismo eje, así que las dos salidas coinciden al ms.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .audio import load_mono

BEAT_SR = 22050


def detect_beats(audio: Path, device: str = "cuda") -> tuple[list[int], list[int]]:
    from beat_this.inference import Audio2Beats

    signal = load_mono(audio, BEAT_SR)
    beats_s, downbeats_s = Audio2Beats(checkpoint_path="final0", device=device, dbn=False)(signal, BEAT_SR)
    return [int(round(b * 1000)) for b in beats_s], [int(round(d * 1000)) for d in downbeats_s]


@dataclass
class TempoMap:
    anchor_beats: np.ndarray  # posición en pulsos de cada ancla
    anchor_ms: np.ndarray  # tiempo en ms de cada ancla
    beats_ms: list[int]  # pulsos detectados
    downbeats_ms: list[int]
    beats_per_measure: int

    @classmethod
    def from_beats(cls, beats_ms: list[int], downbeats_ms: list[int]) -> "TempoMap":
        beats = sorted(set(beats_ms))
        if len(beats) < 4:
            raise ValueError("demasiados pocos pulsos detectados para un mapa de tempo")
        interval = float(np.median(np.diff(beats)))
        while beats and beats[0] < 0.5 * interval:
            beats.pop(0)
        beats = _fill_gaps(beats, interval)
        lead = max(1, int(round(beats[0] / interval)))
        anchor_beats = [0.0] + [float(lead + i) for i in range(len(beats))]
        anchor_ms = [0.0] + [float(b) for b in beats]
        # Extrapolación al final con el tempo de los últimos pulsos.
        tail = float(np.median(np.diff(beats[-8:])))
        anchor_beats.append(anchor_beats[-1] + 10000)
        anchor_ms.append(anchor_ms[-1] + 10000 * tail)

        measure_lengths = np.diff([b for b in downbeats_ms])
        bpm_count = 4
        if len(measure_lengths) >= 2:
            per = np.round(measure_lengths / interval).astype(int)
            per = per[(per >= 2) & (per <= 7)]
            if len(per):
                bpm_count = int(np.bincount(per).argmax())
        if bpm_count == 2:  # Beat This! a veces marca compás cada 2 pulsos en un 4/4
            bpm_count = 4
        return cls(np.array(anchor_beats), np.array(anchor_ms), beats, sorted(downbeats_ms), bpm_count)

    def ms_to_beat(self, ms: float) -> float:
        return float(np.interp(ms, self.anchor_ms, self.anchor_beats))

    def beat_to_ms(self, beat: float) -> int:
        return int(round(np.interp(beat, self.anchor_beats, self.anchor_ms)))

    def bpm_at(self, beat: float) -> float:
        i = int(np.clip(np.searchsorted(self.anchor_beats, beat, side="right") - 1, 0, len(self.anchor_beats) - 2))
        db = self.anchor_beats[i + 1] - self.anchor_beats[i]
        dms = self.anchor_ms[i + 1] - self.anchor_ms[i]
        return 60000.0 * db / dms

    def measure_starts(self, end_beat: float) -> list[float]:
        """Inicio de cada compás en pulsos (de los downbeats; si faltan, cada beats_per_measure)."""
        starts = sorted({round(self.ms_to_beat(d)) for d in self.downbeats_ms})
        if len(starts) < 2:
            starts = [0]
        out = []
        b = float(starts[0])
        # Antes del primer downbeat, compases hacia atrás.
        while b > 0:
            b -= self.beats_per_measure
        b = max(b, 0.0)
        while b < starts[0]:
            out.append(b)
            b += self.beats_per_measure
        for i, s in enumerate(starts):
            out.append(float(s))
            nxt = starts[i + 1] if i + 1 < len(starts) else end_beat
            b = s + self.beats_per_measure
            while b < nxt - 0.5:  # compases sin downbeat detectado
                out.append(float(b))
                b += self.beats_per_measure
        return sorted(set(x for x in out if x < end_beat))


def _fill_gaps(beats: list[int], interval: float) -> list[int]:
    """Tramos sin pulsos detectados (intros, silencios): se rellenan con pulsos
    equiespaciados al tempo de alrededor, para que el tempo no se desplome."""
    out = [beats[0]]
    for b in beats[1:]:
        gap = b - out[-1]
        local = float(np.median(np.diff(out[-8:]))) if len(out) > 2 else interval
        n = int(round(gap / local))
        if gap > 1.5 * local and n >= 2:
            out += [int(round(out[-1] + gap * k / n)) for k in range(1, n)]
        out.append(b)
    return out


def quantize(beat: float) -> float:
    """Ajusta a semicorcheas (1/4 de pulso) o, si encaja claramente mejor, a tresillos (1/3)."""
    q16 = round(beat * 4) / 4
    q12 = round(beat * 3) / 3
    if abs(beat - q12) < abs(beat - q16) * 0.5:
        return q12
    return q16
