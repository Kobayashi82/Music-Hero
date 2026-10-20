"""Reglas del juego: aciertos, fallos, HOPO, sustains, racha y puntuación. Sin Qt ni audio.

Reglas (las de Clone Hero / YARG, simplificadas):
- Una nota se toca con strum dentro de ±HIT_WINDOW_MS de su tiempo y los trastes correctos.
- Nota suelta: solo su traste; con anchor (Ajustes → Juego → Anclar trastes, como en Guitar Hero) cuenta el
  traste más alto pulsado y se pueden "anclar" los de abajo. Acorde: exactos.
- HOPO: basta con cambiar a los trastes correctos (sin strum) si la racha sigue viva.
- Strum sin nota que tocar, o con trastes equivocados: "strum de más", rompe la racha. No cuenta el
  strum que llega justo después de tocar un HOPO sin strum (es costumbre rasguear igual).
- Nota que pasa la ventana sin tocarse: fallo, rompe la racha.
- Sustain: tras acertar, mantener los trastes suma puntos hasta el final; soltar antes lo corta.
- Multiplicador x1..x4, sube cada 10 notas seguidas. 50 puntos por nota (por traste en acordes) y
  25 por pulso de sustain (aprox. 500 ms).
- Star power: las notas de una frase (starpower.phrases) brillan; tocarlas todas llena 1/4 de la barra y
  fallar una apaga la frase. Con la mitad o más se puede activar (activate): multiplicador doble (hasta x8)
  mientras la barra se gasta, 1/32 por pulso de la canción. Las frases tocadas mientras dura la alargan.

Tiempos en ms de la canción (float), el reloj lo da el reproductor.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .chart import Note
from .starpower import BeatClock

HIT_WINDOW_MS = 70.0
NOTE_POINTS = 50
SUSTAIN_POINTS_PER_MS = 25 / 500
STREAK_PER_MULT = 10
MAX_MULT = 4
STAR_PER_PHRASE = 0.25
STAR_MIN = 0.5  # lo que hace falta para activarlo
STAR_BEATS = 32  # la barra llena dura 32 pulsos

PENDING, HIT, MISSED, SKIPPED = 0, 1, 2, 3  # SKIPPED: quedó atrás al cambiar de dificultad, no cuenta


@dataclass
class NoteState:
    note: Note
    state: int = PENDING
    hit_ms: float = 0.0  # cuándo se tocó (para la vista y para medir el desfase)
    sustain_until: float = 0.0  # hasta dónde se ha mantenido el sustain (ms de la canción)
    sustaining: bool = False
    phrase: int = -1  # frase de star power a la que pertenece (-1: ninguna)

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
    star: bool = False  # star power activo: multiplicador doble
    phrases: int = 0  # frases de star power completadas

    @property
    def base_multiplier(self) -> int:
        return min(MAX_MULT, 1 + self.streak // STREAK_PER_MULT)

    @property
    def multiplier(self) -> int:
        return self.base_multiplier * (2 if self.star else 1)

    @property
    def accuracy(self) -> float:
        judged = self.hits + self.misses
        return self.hits / judged if judged else 1.0


def frets_match(held: frozenset[int], frets: tuple[int, ...], anchor: bool = True) -> bool:
    """anchor: en las sueltas vale con que sea el más alto pulsado (los de abajo, anclados)."""
    if not held:
        return False
    if len(frets) == 1 and anchor:
        return max(held) == frets[0]
    return held == frozenset(frets)


class Game:
    def __init__(self, notes: list[Note], window_ms: float = HIT_WINDOW_MS,
                 phrases: list[tuple[int, int]] = (), beats: list[int] = (), anchor: bool = True):
        """phrases: tramos (inicio, fin) de star power en ms; beats: tiempos de los pulsos (gastan la barra);
        anchor: anclar trastes en las notas sueltas (frets_match)."""
        self.notes = [NoteState(n) for n in notes]
        self.window = window_ms
        self.anchor = anchor
        self.stats = Stats()
        self.held: set[int] = set()
        self.next = 0  # primera nota sin juzgar
        self._tap_ms: float | None = None  # tiempo de la última nota tocada sin strum (HOPO)
        self._sustains: list[NoteState] = []
        self.events: list[tuple[str, float, object]] = []  # para la vista: ("hit", ms, nota), ("miss"...), ("overstrum"...),
        # ("phrase", ms, nota) frase completada, ("star", ms, None) activado, ("star_end", ms, None) se acabó
        self.phrase_left: list[int] = []  # notas sin tocar de cada frase; -1 si se ha fallado
        k = 0
        for start, end in phrases:
            while k < len(self.notes) and self.notes[k].note.time_ms < start:
                k += 1
            members = 0
            while k < len(self.notes) and self.notes[k].note.time_ms < end:
                self.notes[k].phrase = len(self.phrase_left)
                members += 1
                k += 1
            if members:
                self.phrase_left.append(members)
        self.energy = 0.0  # la barra: 0..1
        self._clock = BeatClock(list(beats))
        self._drain_beat = 0.0  # posición en pulsos hasta donde ya se ha gastado

    # ---------- entrada ----------

    def fret(self, i: int, down: bool, t: float) -> None:
        self.update(t)
        (self.held.add if down else self.held.discard)(i)
        self._check_sustains(t)
        self._try_tap(t)

    def strum(self, t: float) -> None:
        self.update(t)
        ns = self._candidate(t)
        if ns is not None and frets_match(frozenset(self.held), ns.note.frets, self.anchor):
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
        """Fallos de las notas que ya pasaron, puntos de los sustains y lo que se gasta la barra."""
        while self.next < len(self.notes):
            ns = self.notes[self.next]
            if ns.state != PENDING:
                self.next += 1
            elif ns.note.time_ms + self.window < t:
                self._miss(ns, t)
                self.next += 1
            else:
                break
        self._check_sustains(t)
        self._drain(t)

    def activate(self, t: float) -> bool:
        """Guitarra levantada (o la tecla): activa el star power si hay barra para ello."""
        self.update(t)
        if not self.star_ready:
            return False
        self.stats.star = True
        self._drain_beat = self._clock.pos(t)
        self.events.append(("star", t, None))
        return True

    def is_star(self, ns: NoteState) -> bool:
        """La nota brilla: es de una frase que aún se puede completar (o ya completada)."""
        return ns.phrase >= 0 and self.phrase_left[ns.phrase] >= 0

    @property
    def star_ready(self) -> bool:
        return not self.stats.star and self.energy >= STAR_MIN - 1e-9

    def skip_to(self, t: float) -> None:
        """Empezar a mitad de canción: las notas antes de t no se juegan ni cuentan."""
        while self.next < len(self.notes) and self.notes[self.next].note.time_ms < t:
            ns = self.notes[self.next]
            ns.state = SKIPPED
            if ns.phrase >= 0:
                self.phrase_left[ns.phrase] = -1  # frase empezada antes: ya no se puede completar
            self.next += 1

    @property
    def sustaining_frets(self) -> set[int]:
        return {f for ns in self._sustains if ns.sustaining for f in ns.note.frets}

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
                if frets_match(held, ns.note.frets, self.anchor):
                    return ns
                first = first or ns
        return first

    def _try_tap(self, t: float) -> None:
        if self.stats.streak == 0:
            return
        ns = self._candidate(t)
        if ns is not None and ns.note.hopo and frets_match(frozenset(self.held), ns.note.frets, self.anchor):
            self._hit(ns, t)
            self._tap_ms = t

    def _hit(self, ns: NoteState, t: float) -> None:
        # Las anteriores sin tocar quedan como fallo (se tocó una posterior dentro de la ventana).
        for prev in self.notes[self.next:]:
            if prev is ns:
                break
            if prev.state == PENDING:
                self._miss(prev, t)
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
        if ns.phrase >= 0 and self.phrase_left[ns.phrase] > 0:
            self.phrase_left[ns.phrase] -= 1
            if self.phrase_left[ns.phrase] == 0:  # frase completa
                self.stats.phrases += 1
                self._drain(t)  # lo gastado hasta aquí, antes de sumar
                self.energy = min(1.0, self.energy + STAR_PER_PHRASE)
                self.events.append(("phrase", t, ns))
        self.update(t)

    def _miss(self, ns: NoteState, t: float) -> None:
        ns.state = MISSED
        self.stats.misses += 1
        self.stats.streak = 0
        if ns.phrase >= 0 and self.phrase_left[ns.phrase] > 0:
            self.phrase_left[ns.phrase] = -1  # frase perdida
        self.events.append(("miss", t, ns))

    def _drain(self, t: float) -> None:
        if not self.stats.star:
            return
        pos = self._clock.pos(t)
        if pos <= self._drain_beat:  # los eventos de entrada pueden llegar con un instante algo anterior
            return
        self.energy -= (pos - self._drain_beat) / STAR_BEATS
        self._drain_beat = pos
        if self.energy <= 0:
            self.energy = 0.0
            self.stats.star = False
            self.events.append(("star_end", t, None))

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
