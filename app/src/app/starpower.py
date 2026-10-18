"""Star power: dónde van las frases de notas brillantes, el reloj de pulsos que gasta la barra y la guitarra
levantada (acelerómetro del Wiimote). Sin Qt ni audio; las reglas del juego están en gameplay.py.

Frases (mientras el generador no las guarde en la chart): tramos de 2 compases de los más densos, uno cada
20-30 s. Se eligen con la dificultad más alta para que caigan en el mismo sitio en todas.
"""

from __future__ import annotations

import bisect

from .chart import Note

PHRASE_BARS = 2
FIRST_RANGE_MS = (5000, 20000)  # la primera empieza entre 5 y 20 s después de la primera nota
GAP_RANGE_MS = (15000, 25000)  # y cada una, entre 15 y 25 s después de acabar la anterior (+ ~4 s que dura)
MIN_NOTES = 4  # un tramo con menos notas no vale (silencios, intros): se busca más adelante
DEFAULT_BEAT_MS = 500.0  # sin pulsos en la chart: 120 ppm

# Guitarra levantada. El Wiimote va metido en el cuerpo y su eje Y sigue al mástil (medido con
# tools/poc_wii_tilt.py: tocando, y ≈ 0, a veces −0,4 con la guitarra algo inclinada; con el mástil
# levantado, y ≈ −1). Se filtra para que los golpes del rasgueo no cuenten.
TILT_AXIS = 1
TILT_ON, TILT_OFF = -0.65, -0.45  # ~40° para activarlo; por encima de ~27° se da por bajada (para la próxima)
TILT_SMOOTH = 0.2  # filtro paso bajo por informe (~100 por segundo: unos 50 ms)


def bar_starts(beats: list[tuple[int, bool]]) -> list[int]:
    """Inicios de compás: los marcados en la chart; si no los hay, uno cada 4 pulsos."""
    bars = [t for t, down in beats if down]
    if len(bars) < 2:
        bars = [t for t, _ in beats[::4]]
    return bars


def phrases(notes: list[Note], beats: list[tuple[int, bool]]) -> list[tuple[int, int]]:
    """Tramos (inicio, fin) en ms de la canción, para todas las dificultades."""
    if not notes:
        return []
    times = sorted(n.time_ms for n in notes)
    bars = bar_starts(beats)
    if len(bars) <= PHRASE_BARS:  # sin pulsos: compases de 4 pulsos a 120 ppm
        step = int(DEFAULT_BEAT_MS * 4)
        bars = list(range(times[0] - times[0] % step, times[-1] + step * (PHRASE_BARS + 1), step))
    windows = [(bars[i], bars[i + PHRASE_BARS]) for i in range(len(bars) - PHRASE_BARS)]
    starts = [w[0] for w in windows]

    def count(w: tuple[int, int]) -> int:
        return bisect.bisect_left(times, w[1]) - bisect.bisect_left(times, w[0])

    out: list[tuple[int, int]] = []
    lo, hi = times[0] + FIRST_RANGE_MS[0], times[0] + FIRST_RANGE_MS[1]
    while lo <= times[-1]:
        cands = windows[bisect.bisect_left(starts, lo):bisect.bisect_right(starts, hi)]
        best = max(cands, key=count, default=None)  # max se queda con la primera si empatan
        if best is None or count(best) < MIN_NOTES:
            lo, hi = hi, hi + 10000
            continue
        out.append(best)
        lo, hi = best[1] + GAP_RANGE_MS[0], best[1] + GAP_RANGE_MS[1]
    return out


class BeatClock:
    """Posición en pulsos de un instante (con decimales), para gastar la barra al ritmo de la canción."""

    def __init__(self, beat_times: list[int]):
        self.times = sorted(beat_times)

    def pos(self, t: float) -> float:
        b = self.times
        if len(b) < 2:
            return t / DEFAULT_BEAT_MS
        if t <= b[0]:
            return (t - b[0]) / (b[1] - b[0])
        if t >= b[-1]:
            return len(b) - 1 + (t - b[-1]) / (b[-1] - b[-2])
        i = bisect.bisect_right(b, t) - 1
        return i + (t - b[i]) / max(1, b[i + 1] - b[i])


class Tilt:
    """Detecta el momento en que se levanta el mástil (una vez por levantada: hay que bajarlo para otra)."""

    def __init__(self):
        self.value: float | None = None  # el eje del mástil, filtrado (g)
        self.up = False

    def feed(self, accel: tuple[float, float, float]) -> bool:
        """True justo al levantarlo."""
        if not any(accel):  # informes sin acelerómetro
            return False
        v = accel[TILT_AXIS]
        self.value = v if self.value is None else self.value + TILT_SMOOTH * (v - self.value)
        if not self.up and self.value <= TILT_ON:
            self.up = True
            return True
        if self.up and self.value >= TILT_OFF:
            self.up = False
        return False
