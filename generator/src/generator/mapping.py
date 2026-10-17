"""Notas transcritas -> chart de 5 botones (Experto).

1. Por compás se elige la pista de la que salen las notas: la guitarra si suena;
   si no, piano, "other", voz o bajo, la que más actividad tenga.
2. Los ataques se cuantizan a la rejilla y se agrupan en eventos (nota o acorde).
3. Se limita la densidad (separación mínima entre eventos).
4. Botón por contorno relativo: sube -> derecha, baja -> izquierda, repite -> igual,
   normalizado en una ventana deslizante para no quedarse pegado en un extremo.
5. Acordes -> 2-3 botones; notas largas -> sustain; notas rápidas -> HOPO.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from .model import MELODIC_STEMS, ChartNote, Section, SourceNote
from .rhythm import TempoMap, quantize

if TYPE_CHECKING:  # transcribe carga torch y Basic Pitch; aquí solo hace falta el tipo
    from .transcribe import Transcription


@dataclass
class MapParams:
    min_gap_beats: float = 0.25  # semicorcheas, solo entre notas claras de Basic Pitch
    min_gap_weak_beats: float = 0.5  # corcheas si alguna de las dos es dudosa o un ataque sin nota
    strong_amp: float = 0.45  # amplitud a partir de la cual una nota de Basic Pitch es "clara"
    max_chord_ratio: float = 0.3  # como mucho este porcentaje de acordes
    min_gap_ms: int = 70
    min_amp: float = 0.2
    chord_amp_ratio: float = 0.7  # una nota cuenta para el acorde si es al menos así de fuerte
    hopo_threshold_beats: float = 65 / 192  # el mismo umbral que Clone Hero/YARG por defecto
    sustain_min_beats: float = 0.75
    sustain_min_ms: int = 300
    sustain_gap_beats: float = 0.25  # hueco mínimo entre el fin de un sustain y la siguiente nota
    window_beats: float = 8  # radio de la ventana deslizante para normalizar la altura
    phrase_gap_beats: float = 4  # más separación que esto rompe el contorno
    guitar_min_active: float = 0.5  # fracción del compás con la guitarra sonando para preferirla
    guitar_min_notes: int = 2
    stem_weight: dict[str, float] = field(
        default_factory=lambda: {"guitar": 1.0, "piano": 0.75, "other": 0.65, "vocals": 0.6, "bass": 0.45}
    )


@dataclass
class Event:
    beat: float
    end_beat: float
    pitches: dict[int, float]  # altura -> amplitud
    stem: str
    strong: bool = False  # alguna nota clara de Basic Pitch (no solo un ataque)

    @property
    def amp(self) -> float:
        return max(self.pitches.values())


def choose_sections(
    trans: dict[str, Transcription], tempo: TempoMap, end_beat: float, p: MapParams
) -> list[Section]:
    starts = tempo.measure_starts(end_beat)
    bounds = list(zip(starts, starts[1:] + [end_beat]))
    sections = []
    for a, b in bounds:
        a_ms, b_ms = tempo.beat_to_ms(a), tempo.beat_to_ms(b)
        scores, activity = {}, {}
        for stem in MELODIC_STEMS:
            t = trans.get(stem)
            if t is None:
                continue
            notes = [n for n in t.notes if a_ms <= n.start_ms < b_ms and n.amp >= p.min_amp]
            if not notes:
                scores[stem] = 0.0
                continue
            mask = (t.frame_times_ms >= a_ms) & (t.frame_times_ms < b_ms)
            active = float((t.rms_db[mask] > t.active_db).mean()) if mask.any() else 0.0
            mean_amp = float(np.mean([n.amp for n in notes]))
            scores[stem] = p.stem_weight[stem] * active * min(len(notes), 16) * mean_amp
            activity[stem] = (active, len(notes))
        best = max(scores, key=scores.get) if scores and max(scores.values()) > 0 else ""
        # La guitarra manda siempre que suene de verdad en el compás.
        g_active, g_notes = activity.get("guitar", (0.0, 0))
        if g_active >= p.guitar_min_active and g_notes >= p.guitar_min_notes:
            best = "guitar"
        sections.append(Section(a, b, best, scores))

    # Quitar cambios de un solo compás (A B A -> A A A).
    for i in range(1, len(sections) - 1):
        prev, cur, nxt = sections[i - 1].stem, sections[i].stem, sections[i + 1].stem
        if prev == nxt and cur != prev and sections[i].scores.get(prev, 0) > 0:
            sections[i].stem = prev
    return sections


def _clean_pitches(pitches: dict[int, float], ratio: float) -> dict[int, float]:
    top = max(pitches.values())
    kept = {pch: a for pch, a in pitches.items() if a >= ratio * top}
    # Octavas repetidas (raíz + octava de un power chord) cuentan una vez: se queda la grave.
    out: dict[int, float] = {}
    for pch in sorted(kept):
        if any((pch - q) % 12 == 0 for q in out):
            continue
        out[pch] = kept[pch]
    return out


def build_events(
    trans: dict[str, Transcription], sections: list[Section], tempo: TempoMap, p: MapParams
) -> list[Event]:
    grouped: dict[tuple[float, str], Event] = {}
    for sec in sections:
        if not sec.stem:
            continue
        a_ms, b_ms = tempo.beat_to_ms(sec.start_beat), tempo.beat_to_ms(sec.end_beat)
        for n in trans[sec.stem].notes:
            if not (a_ms <= n.start_ms < b_ms) or n.amp < p.min_amp:
                continue
            qb = round(quantize(tempo.ms_to_beat(n.start_ms)), 6)
            eb = tempo.ms_to_beat(n.end_ms)
            strong = n.origin == "bp" and n.amp >= p.strong_amp
            ev = grouped.get((qb, sec.stem))
            if ev is None:
                grouped[(qb, sec.stem)] = Event(qb, eb, {n.pitch: n.amp}, sec.stem, strong)
            else:
                ev.end_beat = max(ev.end_beat, eb)
                ev.pitches[n.pitch] = max(ev.pitches.get(n.pitch, 0), n.amp)
                ev.strong = ev.strong or strong

    events = sorted(grouped.values(), key=lambda e: e.beat)
    for e in events:
        e.pitches = _clean_pitches(e.pitches, p.chord_amp_ratio)

    # Densidad: si dos eventos quedan demasiado juntos, se queda el más fuerte.
    kept: list[Event] = []
    for e in events:
        if kept:
            last = kept[-1]
            min_gap = p.min_gap_beats if (e.strong and last.strong) else p.min_gap_weak_beats
            too_close = (e.beat - last.beat < min_gap - 1e-6) or (
                tempo.beat_to_ms(e.beat) - tempo.beat_to_ms(last.beat) < p.min_gap_ms
            )
            if too_close:
                if e.amp > last.amp:
                    kept[-1] = e
                continue
        kept.append(e)

    # Tope de acordes: se quedan los que tienen la segunda voz más fuerte; el resto, nota grave.
    chords = [e for e in kept if len(e.pitches) >= 2]
    limit = int(p.max_chord_ratio * len(kept))
    if len(chords) > limit:
        chords.sort(key=lambda e: sorted(e.pitches.values())[-2], reverse=True)
        for e in chords[limit:]:
            low = min(e.pitches)
            e.pitches = {low: e.pitches[low]}
    return kept


def assign_frets(events: list[Event], tempo: TempoMap, p: MapParams) -> list[ChartNote]:
    reps = np.array([min(e.pitches) for e in events], dtype=float)
    beats = np.array([e.beat for e in events])
    notes: list[ChartNote] = []
    prev_rep = prev_fret = None
    prev_beat = -1e9
    recent: dict[int, tuple[int, float]] = {}  # altura -> (botón, pulso) para repetir riffs igual

    for i, e in enumerate(events):
        rep = reps[i]
        target = _rank_fret(rep, reps[np.abs(beats - e.beat) <= p.window_beats])
        fret = target

        in_phrase = prev_fret is not None and e.beat - prev_beat <= p.phrase_gap_beats
        if in_phrase:
            d = rep - prev_rep
            seen = recent.get(int(rep))
            if d == 0:
                fret = prev_fret
            elif seen is not None and e.beat - seen[1] <= p.window_beats and np.sign(seen[0] - prev_fret) == np.sign(d):
                fret = seen[0]  # misma altura que hace poco: mismo botón (los riffs se repiten igual)
            else:
                fret = _contour_step(prev_fret, d, target)

        pitches = sorted(e.pitches)
        if len(pitches) >= 2:
            width = 2 if len(pitches) == 2 else 3
            step = 1 if width == 3 or (pitches[1] - pitches[0]) <= 7 else 2
            base = min(fret, 4 - step * (width - 1))
            frets = [base + k * step for k in range(width)]
            fret = base
        else:
            frets = [fret]

        notes.append(ChartNote(tempo.beat_to_ms(e.beat), frets, beat=e.beat, end_beat=e.end_beat,
                               pitch=int(rep), stem=e.stem))
        recent[int(rep)] = (fret, e.beat)
        prev_rep, prev_fret, prev_beat = rep, fret, e.beat

    _sustains_and_hopos(notes, tempo, p)
    return notes


def _contour_step(prev_fret: int, d: float, target: int) -> int:
    """Siguiente botón respetando la dirección del intervalo.

    El paso ideal crece con el intervalo (1 botón hasta 4 semitonos, 2 hasta 9,
    3 más allá); entre los botones en esa dirección se elige el que mejor combina
    ese paso con el botón "objetivo" del reparto por orden, para no ir a la deriva
    hacia los extremos.
    """
    direction = 1 if d > 0 else -1
    size = 1 if abs(d) <= 4 else 2 if abs(d) <= 9 else 3
    options = range(prev_fret + 1, 5) if direction > 0 else range(0, prev_fret)
    if not options:  # ya en el extremo: mejor el objetivo que repetir botón con otra altura
        return target if target != prev_fret else max(0, min(4, prev_fret - direction))
    ideal = prev_fret + direction * size
    return min(options, key=lambda f: abs(f - ideal) + 0.5 * abs(f - target))


def _rank_fret(rep: float, window: np.ndarray) -> int:
    """Botón por orden de altura dentro de la ventana, no por distancia en semitonos.

    Con k alturas distintas (k <= 5) se usan k botones seguidos y centrados: así
    notas vecinas quedan en botones vecinos y no se salta de verde a naranja.
    Con más de 5, se reparten las alturas (las raras cuentan menos) en los 5 botones.
    """
    values, counts = np.unique(window, return_counts=True)
    # Alturas sueltas (errores de transcripción) no deben estirar el rango.
    common = values[counts >= max(1, 0.05 * counts.sum())]
    values = common if len(common) else values
    k = len(values)
    rank = int(np.searchsorted(values, rep))
    rank = min(rank, k - 1)
    if k <= 5:
        return (5 - k) // 2 + rank
    return int(round(rank / (k - 1) * 4))


def _sustains_and_hopos(notes: list[ChartNote], tempo: TempoMap, p: MapParams) -> None:
    for i, n in enumerate(notes):
        nxt = notes[i + 1].beat if i + 1 < len(notes) else float("inf")
        end = min(round(n.end_beat * 4) / 4, nxt - p.sustain_gap_beats)
        length_ms = tempo.beat_to_ms(end) - n.time_ms
        if end - n.beat >= p.sustain_min_beats and length_ms >= p.sustain_min_ms:
            n.sustain_ms = length_ms
            n.end_beat = end
        else:
            n.end_beat = n.beat

        if i > 0 and len(n.frets) == 1:
            prev = notes[i - 1]
            n.hopo = (n.beat - prev.beat <= p.hopo_threshold_beats + 1e-6) and n.frets[0] not in prev.frets


def map_expert(
    trans: dict[str, Transcription], tempo: TempoMap, end_beat: float, p: MapParams | None = None
) -> tuple[list[ChartNote], list[Section], list[SourceNote]]:
    p = p or MapParams()
    sections = choose_sections(trans, tempo, end_beat, p)
    events = build_events(trans, sections, tempo, p)
    notes = assign_frets(events, tempo, p)
    source = [n for t in trans.values() for n in t.notes]
    return notes, sections, source
