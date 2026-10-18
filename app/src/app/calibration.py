"""Calibración del retardo de audio: suenan clics a ritmo fijo y se rasguea con ellos.

Si lo que oyes llega L ms tarde de lo que cree el reproductor (altavoz Bluetooth, driver), rasgueas L ms
tarde de cada clic según su reloj: la mediana de (strum - clic) es lo que hay que sumar a audio_offset_ms.
La pantalla no enseña nada al ritmo para que se siga al oído y no a la vista.
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
    clicks = np.array((clicks_ms or click_times_ms())[COUNT_IN:])
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
