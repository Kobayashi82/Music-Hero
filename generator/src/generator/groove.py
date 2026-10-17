"""Ritmo automático "como lo tamborilearía alguien": toques sintéticos.

Comparado con ritmos marcados a mano (tools/analyze_taps.py): donde hay batería,
lo que se tamborilea coincide sobre todo con sus golpes (más que con la voz o
la guitarra), a unos 2-2,5 toques por segundo. Donde no hay batería, pocas notas
en los acentos fuertes del conjunto, largas si el sonido se mantiene.

Devuelve toques (inicio, fin) en ms, igual que la grabadora, así que el resto
del generador los trata como si fueran marcados a mano.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .audio import load_mono
from .feel import Feel


@dataclass
class GrooveParams:
    drum_rate: float = 2.5  # toques por segundo con batería
    calm_rate: float = 1.0  # toques por segundo sin batería
    min_gap_ms: int = 180
    calm_min_gap_ms: int = 400
    window_s: float = 4.0  # el presupuesto se reparte por ventanas de este tamaño
    drums_present_db: float = -24  # batería - mezcla por encima de esto = hay batería
    onset_delta: float = 0.15
    calm_accent: float = 0.6  # acento mínimo del conjunto sin batería
    long_gap_ms: int = 600  # hueco a partir del cual la nota puede ser larga...
    long_max_drop_db: float = 6  # ...si el volumen no cae más que esto durante el hueco
    short_ms: int = 100


def _drum_onsets(drums: Path, p: GrooveParams) -> tuple[np.ndarray, np.ndarray]:
    import librosa
    import scipy.ndimage as nd

    from .transcribe import AUDIO_SAMPLE_RATE as SR, FFT_HOP as HOP

    y = load_mono(drums, SR)
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    en = np.clip(env / (nd.percentile_filter(env, 95, size=int(SR / HOP * 6)) + 1e-6), 0, 1.5)
    pk = librosa.util.peak_pick(en, pre_max=3, post_max=3, pre_avg=12, post_avg=12, delta=p.onset_delta, wait=5)
    pk = pk[env[pk] >= np.percentile(env, 60)]
    return librosa.frames_to_time(pk, sr=SR, hop_length=HOP) * 1000, en[pk]


def auto_taps(drums: Path, feel: Feel, duration_ms: int, p: GrooveParams | None = None) -> list[tuple[int, int]]:
    p = p or GrooveParams()
    drum_t, drum_s = _drum_onsets(drums, p)

    def drums_present(t: np.ndarray) -> np.ndarray:
        return np.interp(t, feel.times_ms, feel.drum_rel_db) > p.drums_present_db

    keep = drums_present(drum_t)
    drum_t, drum_s = drum_t[keep], drum_s[keep]

    a = feel.mix_accent
    is_peak = (a[1:-1] > a[:-2]) & (a[1:-1] >= a[2:]) & (a[1:-1] >= p.calm_accent)
    calm_t = feel.times_ms[1:-1][is_peak]
    calm_s = a[1:-1][is_peak]
    calm = ~drums_present(calm_t)
    calm_t, calm_s = calm_t[calm], calm_s[calm]

    starts: list[float] = []
    w = p.window_s * 1000
    for w0 in np.arange(0, duration_ms, w):
        # Una ventana es "con batería" si la mayoría del tiempo la hay.
        frames = (feel.times_ms >= w0) & (feel.times_ms < w0 + w)
        with_drums = frames.any() and np.mean(feel.drum_rel_db[frames] > p.drums_present_db) >= 0.5
        t, s = (drum_t, drum_s) if with_drums else (calm_t, calm_s)
        rate, gap = (p.drum_rate, p.min_gap_ms) if with_drums else (p.calm_rate, p.calm_min_gap_ms)
        idx = np.where((t >= w0) & (t < w0 + w))[0]
        chosen: list[float] = []
        for i in idx[np.argsort(-s[idx])]:
            if len(chosen) >= int(round(rate * p.window_s)):
                break
            if all(abs(t[i] - c) >= gap for c in chosen) and all(abs(t[i] - c) >= gap for c in starts[-3:]):
                chosen.append(float(t[i]))
        starts += sorted(chosen)

    starts.sort()
    taps = []
    for i, s in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else s + p.short_ms
        end = s + p.short_ms
        if nxt - s >= p.long_gap_ms:
            seg = (feel.times_ms >= s) & (feel.times_ms < nxt)
            at = int(np.clip(np.searchsorted(feel.times_ms, s + 50), 0, len(feel.times_ms) - 1))
            if seg.any() and feel.mix_db[seg].mean() >= feel.mix_db[at] - p.long_max_drop_db:
                end = nxt - min(250, 0.3 * (nxt - s))
        taps.append((int(round(s)), int(round(end))))
    return taps
