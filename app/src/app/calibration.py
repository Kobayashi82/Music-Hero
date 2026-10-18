"""Calibración del retardo, como en Band Hero: bajan notas por la autopista, cada una suena (un clic) al
llegar a la línea y se rasguea en ese momento.

Si lo que oyes y ves llega L ms tarde de lo que cree el reproductor (altavoz Bluetooth, driver, monitor),
rasgueas L ms tarde de cada clic según su reloj: la mediana de (strum - clic) es lo que hay que sumar a
audio_offset_ms (que mueve a la vez el sonido, la imagen y los aciertos). Los 4 clics de entrada, más
agudos y sin nota, solo marcan el ritmo.
"""

from __future__ import annotations

import numpy as np

BPM = 100
COUNT_IN = 4  # clics de entrada (más agudos), no se miden
CLICKS = 16
LEAD_MS = 1000
MAX_DEV_MS = 250  # strums más lejos de un clic no cuentan
MIN_TAPS = 8


def click_times_ms() -> list[float]:
    period = 60000 / BPM
    return [LEAD_MS + i * period for i in range(COUNT_IN + CLICKS)]


def scored_clicks_ms() -> list[float]:
    """Los clics con nota, los que se miden."""
    return click_times_ms()[COUNT_IN:]


def nearest(strum_ms: float) -> int | None:
    """Índice (en scored_clicks_ms) del clic que toca ese strum, o None si no está cerca de ninguno."""
    clicks = np.array(scored_clicks_ms())
    i = int(np.argmin(np.abs(clicks - strum_ms)))
    return i if abs(strum_ms - clicks[i]) <= MAX_DEV_MS else None


def click_track(sr: int) -> np.ndarray:
    """Audio estéreo float32 con los clics de click_times_ms()."""
    times = click_times_ms()
    out = np.zeros((int((times[-1] + 800) / 1000 * sr), 2), dtype=np.float32)
    n = int(0.03 * sr)
    t = np.arange(n) / sr
    env = np.exp(-t * 120)
    for i, ms in enumerate(times):
        freq = 1600 if i < COUNT_IN else 1000
        a = int(ms / 1000 * sr)
        out[a:a + n] += (0.6 * np.sin(2 * np.pi * freq * t) * env)[:, None]
    return out


def measure(strums_ms: list[float], clicks_ms: list[float] | None = None) -> tuple[float, int, float] | None:
    """(desfase mediano en ms, strums que cuentan, dispersión en ms) o None si hay pocos."""
    clicks = np.array(clicks_ms or scored_clicks_ms())
    devs = []
    for s in strums_ms:
        d = s - clicks[np.argmin(np.abs(clicks - s))]
        if abs(d) <= MAX_DEV_MS:
            devs.append(d)
    if len(devs) < MIN_TAPS:
        return None
    devs = np.array(devs)
    med = float(np.median(devs))
    return med, len(devs), float(np.median(np.abs(devs - med)))
