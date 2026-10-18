"""Reproductor propio: suena la canción y da su posición exacta (el reloj del juego).

En cada bloque de audio se apunta qué muestra es la primera y en qué instante de time.perf_counter()
llegará al altavoz (latencia de salida que da WASAPI). Con eso, cualquier instante (p. ej. el de una
pulsación) se traduce a ms de la canción sin esperar al siguiente bloque. offset_ms (calibración)
corrige lo que la API no ve: el altavoz Bluetooth, el driver...
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf


def wasapi_output() -> int | None:
    for i, h in enumerate(sd.query_hostapis()):
        if "WASAPI" in h["name"] and h["default_output_device"] >= 0:
            return h["default_output_device"]
    return None


class Player:
    def __init__(self, source: Path | tuple[np.ndarray, int], offset_ms: float = 0.0, lead_in_ms: float = 2000.0,
                 volume: float = 1.0):
        """source: archivo de audio o (muestras float32, frecuencia)."""
        if isinstance(source, tuple):
            audio, self.sr = source
            audio = audio.reshape(len(audio), -1)
        else:
            audio, self.sr = sf.read(str(source), dtype="float32", always_2d=True)
        self.audio = audio[:, :2] if audio.shape[1] >= 2 else np.repeat(audio, 2, axis=1)
        self.duration_ms = len(self.audio) / self.sr * 1000
        self.offset_ms = offset_ms
        self.volume = volume
        self._frame = -int(lead_in_ms / 1000 * self.sr)  # cuenta atrás en silencio antes de empezar
        self._playing = False
        self._lock = threading.Lock()
        self._anchor: tuple[int, float] | None = None  # (muestra, perf_counter en que suena)
        device = wasapi_output()
        extra = sd.WasapiSettings(auto_convert=True) if device is not None else None
        self.stream = sd.OutputStream(samplerate=self.sr, channels=2, dtype="float32", device=device,
                                      latency="low", extra_settings=extra, callback=self._callback)
        self.stream.start()

    # ---------- control ----------

    def play(self) -> None:
        with self._lock:
            self._playing = True

    def pause(self) -> None:
        with self._lock:
            self._playing = False
            self._anchor = None

    def toggle(self) -> None:
        self.pause() if self._playing else self.play()

    @property
    def playing(self) -> bool:
        return self._playing

    def seek(self, ms: float) -> None:
        with self._lock:
            self._frame = int(ms / 1000 * self.sr)
            self._anchor = None

    @property
    def finished(self) -> bool:
        return self._frame >= len(self.audio)

    def close(self) -> None:
        self.stream.stop()
        self.stream.close()

    # ---------- reloj ----------

    def position_ms(self, at: float | None = None) -> float:
        """ms de la canción que suenan (o sonaban) en el instante at de perf_counter (ahora si None)."""
        at = time.perf_counter() if at is None else at
        anchor = self._anchor
        if anchor is None or not self._playing:
            return self._frame / self.sr * 1000 - self.offset_ms
        frame, when = anchor
        return (frame / self.sr + (at - when)) * 1000 - self.offset_ms

    def _callback(self, out: np.ndarray, frames: int, time_info, status) -> None:
        now = time.perf_counter()
        with self._lock:
            if not self._playing:
                out.fill(0)
                return
            start = self._frame
            out.fill(0)
            a, b = max(0, start), min(len(self.audio), start + frames)
            if b > a:
                out[a - start:b - start] = self.audio[a:b] * self.volume
            self._frame = start + frames
            latency = time_info.outputBufferDacTime - time_info.currentTime
            if not 0 <= latency < 1:  # algunas APIs no la dan
                latency = self.stream.latency
            self._anchor = (start, now + latency)
