"""La "sensación" de la canción: energía por tramo y acentos.

La chart no transcribe todas las notas: toca lo que se siente. Para eso hace
falta saber cuánta energía tiene cada tramo (decide cuántas notas caben) y dónde
están los acentos (decide cuáles se quedan).

Energía: sobre todo lo presente que está la batería respecto a la mezcla (en
una balada la batería va muy por debajo; en rock o punk, casi al nivel de la
mezcla), y algo de lo fuerte que suena el tramo dentro de la propia canción.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .audio import load_mono

SR = 22050
HOP = 256


@dataclass
class Feel:
    times_ms: np.ndarray
    mix_accent: np.ndarray  # 0..1, fuerza de ataque del conjunto normalizada por ventanas
    drum_accent: np.ndarray  # 0..1, lo mismo para la batería
    mix_db: np.ndarray
    drum_rel_db: np.ndarray  # batería - mezcla, en dB

    def _span(self, a_ms: float, b_ms: float) -> slice:
        i, j = np.searchsorted(self.times_ms, [a_ms, b_ms])
        i = min(int(i), len(self.times_ms) - 1)  # el último compás puede pasar del final del audio
        return slice(i, max(int(j), i + 1))

    def energy(self, a_ms: float, b_ms: float) -> float:
        s = self._span(a_ms, b_ms)
        # Mediana por tramo de batería - mezcla: unos -26 dB en una balada con la batería
        # de fondo, -10..-12 dB en rock/punk/pop con batería. -24 dB -> 0, -10 dB -> 1.
        drum = np.clip((np.median(self.drum_rel_db[s]) + 24) / 14, 0, 1)
        loud_ref = np.percentile(self.mix_db, 90)
        loud = np.clip((np.median(self.mix_db[s]) - (loud_ref - 12)) / 12, 0, 1)
        return float(0.75 * drum + 0.25 * loud)

    def accent(self, t_ms: float) -> tuple[float, float]:
        """Acento del conjunto y de la batería en ±30 ms alrededor de t."""
        s = self._span(t_ms - 30, t_ms + 30)
        return float(self.mix_accent[s].max()), float(self.drum_accent[s].max())


def _accent_curve(y: np.ndarray, librosa) -> np.ndarray:
    import scipy.ndimage as nd

    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    scale = nd.percentile_filter(env, 95, size=int(SR / HOP * 8)) + 1e-6
    return np.clip(env / scale, 0, 1)


def _db_curve(y: np.ndarray, n: int, librosa) -> np.ndarray:
    rms = librosa.feature.rms(y=y, frame_length=HOP * 8, hop_length=HOP)[0]
    db = 20 * np.log10(rms + 1e-9)
    db = np.convolve(db, np.ones(43) / 43, mode="same")  # ~0,5 s
    return np.pad(db, (0, max(0, n - len(db))), mode="edge")[:n]


def analyze(audio: Path, drums: Path) -> Feel:
    import librosa

    mix = load_mono(audio, SR)
    dr = load_mono(drums, SR)
    n = min(len(mix), len(dr))
    mix, dr = mix[:n], dr[:n]
    mix_acc = _accent_curve(mix, librosa)
    drum_acc = _accent_curve(dr, librosa)
    frames = min(len(mix_acc), len(drum_acc))
    mix_db = _db_curve(mix, frames, librosa)
    drum_db = _db_curve(dr, frames, librosa)
    times = librosa.frames_to_time(np.arange(frames), sr=SR, hop_length=HOP) * 1000
    return Feel(times, mix_acc[:frames], drum_acc[:frames], mix_db, drum_db - mix_db)
