"""Retardo de un reproductor externo medido con el audio del sistema (WASAPI loopback).

Se capturan unos segundos de lo que suena y se buscan en el archivo de la canción alrededor de la posición que
dice el reproductor: la diferencia es lo que tarda en oírse (su búfer). Con AIMP sale ~230 ms y muy estable.
El loopback no ve el retardo del propio altavoz (Bluetooth...): ese lo cubre la calibración del juego.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np
import soundfile as sf

from .i18n import t

SEARCH_MS = (-300, 1500)  # retardos posibles
MIN_QUALITY = 0.5  # correlación normalizada mínima (con otro sonido a la vez o un ecualizador fuerte, baja)


def capture(seconds: float) -> tuple[np.ndarray, int, float]:
    """(audio mono, frecuencia, perf_counter del final de la captura) de la salida por defecto."""
    import pyaudiowpatch as pyaudio

    pa = pyaudio.PyAudio()
    try:
        out = pa.get_device_info_by_index(pa.get_host_api_info_by_type(pyaudio.paWASAPI)["defaultOutputDevice"])
        dev = next(d for d in pa.get_loopback_device_info_generator() if out["name"] in d["name"])
        sr, ch = int(dev["defaultSampleRate"]), dev["maxInputChannels"]
        stream = pa.open(format=pyaudio.paFloat32, channels=ch, rate=sr, input=True,
                         input_device_index=dev["index"], frames_per_buffer=480)
        chunks, got, end = [], 0, 0.0
        while got < seconds * sr:
            data = stream.read(480, exception_on_overflow=False)
            end = time.perf_counter()  # lo leído acaba de sonar (salvo el búfer de captura, ~10 ms)
            chunks.append(np.frombuffer(data, np.float32).reshape(-1, ch).mean(axis=1))
            got += len(chunks[-1])
        stream.close()
        return np.concatenate(chunks), sr, end
    finally:
        pa.terminate()


def song_audio(path: str, sr: int) -> np.ndarray:
    import soxr

    data, file_sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    return soxr.resample(mono, file_sr, sr) if file_sr != sr else mono


def lag_ms(captured: np.ndarray, song: np.ndarray, sr: int, end_pos_ms: float) -> tuple[float, float]:
    """(retardo en ms, calidad) de la captura frente a la canción; end_pos_ms = posición del reproductor
    cuando acabó la captura. Retardo positivo = se oye más tarde de lo que dice el reproductor."""
    n = len(captured)
    lo = int((end_pos_ms - SEARCH_MS[1]) / 1000 * sr) - n
    hi = int((end_pos_ms - SEARCH_MS[0]) / 1000 * sr)
    seg = song[max(0, lo):max(0, hi)]
    if len(seg) < n:
        raise ValueError(t("la posición está fuera de la canción"))
    size = 1 << int(np.ceil(np.log2(len(seg) + n)))
    corr = np.fft.irfft(np.fft.rfft(seg, size) * np.conj(np.fft.rfft(captured, size)), size)[:len(seg) - n + 1]
    energy = np.sqrt(np.convolve(seg ** 2, np.ones(n), "valid")) * np.sqrt((captured ** 2).sum()) + 1e-9
    score = corr / energy
    k = int(np.argmax(score))
    heard_end_ms = (max(0, lo) + k + n) / sr * 1000
    return end_pos_ms - heard_end_ms, float(score[k])


def measure(audio_file: str, position_at: Callable[[float], float], seconds: float = 4.0, times: int = 2,
            log: Callable[[str], None] | None = None) -> float | None:
    """Mediana de los retardos medidos (None si ninguno es fiable). position_at(perf_counter) -> ms del
    reproductor en ese instante, sin corregir."""
    song, lags = None, []
    for _ in range(times):
        captured, sr, end = capture(seconds)
        if np.abs(captured).max() < 1e-4:
            continue  # silencio (pausa, o suena por otra salida)
        if song is None:
            song = song_audio(audio_file, sr)
        lag, quality = lag_ms(captured, song, sr, position_at(end))
        if log:
            log(t("retardo {lag:+.0f} ms (correlación {q:.2f})", lag=lag, q=quality))
        if quality >= MIN_QUALITY:
            lags.append(lag)
    return float(np.median(lags)) if lags else None
