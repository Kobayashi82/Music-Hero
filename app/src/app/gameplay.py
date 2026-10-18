"""Reglas del juego: aciertos, fallos, HOPO, sustains, racha y puntuación. Sin Qt ni audio.

Reglas (las de Clone Hero / YARG, simplificadas):
- Una nota se toca con strum dentro de ±HIT_WINDOW_MS de su tiempo y los trastes correctos.
- Nota suelta: cuenta el traste más alto pulsado (se pueden "anclar" los de abajo). Acorde: exactos.
- HOPO: basta con cambiar a los trastes correctos (sin strum) si la racha sigue viva.
- Strum sin nota que tocar, o con trastes equivocados: "strum de más", rompe la racha. No cuenta el
  strum que llega justo después de tocar un HOPO sin strum (es costumbre rasguear igual).
- Nota que pasa la ventana sin tocarse: fallo, rompe la racha.
- Sustain: tras acertar, mantener los trastes suma puntos hasta el final; soltar antes lo corta.
- Multiplicador x1..x4, sube cada 10 notas seguidas. 50 puntos por nota (por traste en acordes) y
  25 por pulso de sustain (aprox. 500 ms).

Tiempos en ms de la canción (float), el reloj lo da el reproductor.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .chart import Note

HIT_WINDOW_MS = 70.0
NOTE_POINTS = 50
SUSTAIN_POINTS_PER_MS = 25 / 500
STREAK_PER_MULT = 10
MAX_MULT = 4

PENDING, HIT, MISSED = 0, 1, 2


@dataclass
class NoteState:
    note: Note
    state: int = PENDING
    hit_ms: float = 0.0  # cuándo se tocó (para la vista y para medir el desfase)
    sustain_until: float = 0.0  # hasta dónde se ha mantenido el sustain (ms de la canción)
    sustaining: bool = False

    @property
    def end_ms(self) -> float:
        return self.note.time_ms + self.note.sustain_ms


@dataclass
class Stats:
    hits: int = 0
    misses: int = 0
    overstrums: int = 0
    streak: int = 0
    best_streak: int = 0
    score: float = 0.0
    offsets: list[float] = field(default_factory=list)  # strum - nota, ms (para calibrar)

    @property
    def multiplier(self) -> int:
        return min(MAX_MULT, 1 + self.streak // STREAK_PER_MULT)

    @property
    def accuracy(self) -> float:
        judged = self.hits + self.misses
        return self.hits / judged if judged else 1.0


def frets_match(held: frozenset[int], frets: tuple[int, ...]) -> bool:
    if not held:
        return False
    if len(frets) == 1:
        return max(held) == frets[0]
    return held == frozenset(frets)


class Game:
    def __init__(self, notes: list[Note], window_ms: float = HIT_WINDOW_MS):
        self.notes = [NoteState(n) for n in notes]
        self.window = window_ms
        self.stats = Stats()
        self.held: set[int] = set()
        self.next = 0  # primera nota sin juzgar
        self._tap_ms: float | None = None  # tiempo de la última nota tocada sin strum (HOPO)
        self._sustains: list[NoteState] = []
        self.events: list[tuple[str, float, object]] = []  # para la vista: ("hit", ms, nota), ("miss"...), ("overstrum"...)

    # ---------- entrada ----------

    def fret(self, i: int, down: bool, t: float) -> None:
        self.update(t)
        (self.held.add if down else self.held.discard)(i)
        self._check_sustains(t)
        self._try_tap(t)

    def strum(self, t: float) -> None:
        self.update(t)
        ns = self._candidate(t)
        if ns is not None and frets_match(frozenset(self.held), ns.note.frets):
            self._hit(ns, t)
            self.stats.offsets.append(t - ns.note.time_ms)
            self._tap_ms = None
            return
        if self._tap_ms is not None and abs(t - self._tap_ms) <= self.window:
            self._tap_ms = None  # strum de cortesía tras un HOPO
            return
        self.stats.overstrums += 1
        self.stats.streak = 0
        for s in self._sustains:  # un strum de más corta el sustain que suena
            s.sustaining = False
        self._sustains.clear()
        self.events.append(("overstrum", t, ns))

    # ---------- tiempo ----------

    def update(self, t: float) -> None:
        """Fallos de las notas que ya pasaron y puntos de los sustains."""
        while self.next < len(self.notes):
            ns = self.notes[self.next]
            if ns.state != PENDING:
                self.next += 1
            elif ns.note.time_ms + self.window < t:
                ns.state = MISSED
                self.stats.misses += 1
                self.stats.streak = 0
                self.events.append(("miss", t, ns))
                self.next += 1
            else:
                break
        self._check_sustains(t)

    @property
    def finished(self) -> bool:
        return self.next >= len(self.notes) and not self._sustains

    # ---------- interno ----------

    def _candidate(self, t: float) -> NoteState | None:
        """Nota a tocar: la primera sin tocar dentro de la ventana que encaje con los trastes pulsados;
        si ninguna encaja, la primera de la ventana (para el aviso de strum de más)."""
        held = frozenset(self.held)
        first = None
        for ns in self.notes[self.next:]:
            if ns.note.time_ms - self.window > t:
                break
            if ns.state == PENDING and abs(ns.note.time_ms - t) <= self.window:
                if frets_match(held, ns.note.frets):
                    return ns
                first = first or ns
        return first

    def _try_tap(self, t: float) -> None:
        if self.stats.streak == 0:
            return
        ns = self._candidate(t)
        if ns is not None and ns.note.hopo and frets_match(frozenset(self.held), ns.note.frets):
            self._hit(ns, t)
            self._tap_ms = t

    def _hit(self, ns: NoteState, t: float) -> None:
        # Las anteriores sin tocar quedan como fallo (se tocó una posterior dentro de la ventana).
        for prev in self.notes[self.next:]:
            if prev is ns:
                break
            if prev.state == PENDING:
                prev.state = MISSED
                self.stats.misses += 1
                self.stats.streak = 0
                self.events.append(("miss", t, prev))
        ns.state = HIT
        ns.hit_ms = t
        self.stats.hits += 1
        self.stats.score += NOTE_POINTS * len(ns.note.frets) * self.stats.multiplier  # el de antes de esta nota
        self.stats.streak += 1
        self.stats.best_streak = max(self.stats.best_streak, self.stats.streak)
        if ns.note.sustain_ms > 0:
            ns.sustaining = True
            ns.sustain_until = ns.note.time_ms
            self._sustains.append(ns)
        self.events.append(("hit", t, ns))
        self.update(t)

    def _check_sustains(self, t: float) -> None:
        held = frozenset(self.held)
        for ns in list(self._sustains):
            end = min(t, ns.end_ms)
            if end > ns.sustain_until:
                self.stats.score += (end - ns.sustain_until) * SUSTAIN_POINTS_PER_MS * self.stats.multiplier
                ns.sustain_until = end
            # Mantener: todos los trastes de la nota pulsados (en sueltas se admiten los de abajo).
            ok = bool(held) and set(ns.note.frets) <= held and (len(ns.note.frets) > 1 or max(held) == ns.note.frets[0])
            if t >= ns.end_ms or not ok:
                ns.sustaining = False
                self._sustains.remove(ns)
