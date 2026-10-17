"""Notas transcritas -> chart de 5 botones (Experto).

La chart toca la sensación de la canción, no todas sus notas:

1. Por compás se elige la pista de la que salen las notas: la guitarra si suena;
   si no, piano, "other", voz o bajo, la que más actividad tenga.
2. Los ataques se cuantizan a la rejilla y se agrupan en eventos (nota o acorde).
3. Cada compás tiene un presupuesto de notas según su energía (feel.py) y se
   quedan los eventos que más se sienten: tiempos fuertes, acentos del conjunto
   y de la batería, notas fuertes y largas.
4. Botón por contorno relativo: sube -> derecha, baja -> izquierda, repite -> igual,
   normalizado en una ventana deslizante para no quedarse pegado en un extremo.
5. Acordes (pocos, en los acentos) -> 2-3 botones; notas largas -> sustain;
   notas rápidas -> HOPO.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from .model import MELODIC_STEMS, ChartNote, Section, SourceNote
from .rhythm import TempoMap, quantize

if TYPE_CHECKING:  # transcribe carga torch y Basic Pitch; aquí solo hace falta el tipo
    from .feel import Feel
    from .transcribe import Transcription


@dataclass
class MapParams:
    # Presupuesto: notas por pulso según la energía del compás (0 -> min, 1 -> max).
    notes_per_beat_min: float = 0.75
    notes_per_beat_max: float = 2.25
    default_energy: float = 0.7  # sin análisis de energía (tests)
    min_gap_beats: float = 0.25  # semicorcheas: solo en tramos enérgicos y entre notas claras
    min_gap_weak_beats: float = 0.5  # corcheas en el resto
    fast_energy: float = 0.75  # energía a partir de la cual se permiten semicorcheas
    strong_amp: float = 0.45  # amplitud a partir de la cual una nota de Basic Pitch es "clara"
    chord_ratio_min: float = 0.08  # porcentaje de acordes en una canción tranquila...
    chord_ratio_max: float = 0.25  # ...y en una enérgica
    triad_energy: float = 0.8  # acordes de 3 botones solo con esta energía
    fast_step_beats: float = 0.5  # notas más juntas que esto se mueven como mucho 1 botón
    # Relleno de groove (tramos enérgicos con pocas notas transcritas)
    fill_energy: float = 0.6  # solo con al menos esta energía
    fill_below: float = 0.7  # si las notas elegidas no llegan a esta fracción del presupuesto
    fill_accent: float = 0.35  # acento mínimo (batería o conjunto) para poner una nota
    fill_max_hold_beats: float = 4  # repetir una nota como mucho hasta este número de pulsos después
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
    # Notas por segundo como mucho en cualquier ventana de 2 s (charts del modelo). Algo por encima
    # del p90 de las charts humanas (13 / 7 / 5 / 3,5): solo recorta excesos.
    max_nps: dict[str, float] = field(
        default_factory=lambda: {"expert": 14.0, "hard": 8.0, "medium": 5.0, "easy": 3.5}
    )


@dataclass
class Event:
    beat: float
    end_beat: float
    pitches: dict[int, float]  # altura -> amplitud
    stem: str
    strong: bool = False  # alguna nota clara de Basic Pitch (no solo un ataque)
    salience: float = 0.0  # cuánto se siente al escuchar (decide qué notas entran)

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
    trans: dict[str, Transcription], sections: list[Section], tempo: TempoMap, p: MapParams,
    feel: Feel | None = None,
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
    measure_starts = {round(sec.start_beat, 6) for sec in sections}
    for e in events:
        e.pitches = _clean_pitches(e.pitches, p.chord_amp_ratio)
        e.salience = _salience(e, tempo, feel, measure_starts)

    kept: list[Event] = []
    for sec in sections:
        a_ms, b_ms = tempo.beat_to_ms(sec.start_beat), tempo.beat_to_ms(sec.end_beat)
        sec.energy = feel.energy(a_ms, b_ms) if feel is not None else p.default_energy
        picked = _pick(events, sec, tempo, p)
        if feel is not None and sec.stem:
            picked += _groove_fill(picked, events, sec, trans[sec.stem], tempo, feel, p, measure_starts)
        kept += picked

    kept.sort(key=lambda e: e.beat)
    _limit_chords(kept, sections, p)
    return kept


def _salience(e: Event, tempo: TempoMap, feel: Feel | None, measure_starts: set[float]) -> float:
    """Cuánto se siente un evento: tiempo fuerte, acento del conjunto y la batería, fuerza y duración."""
    frac = e.beat % 1
    if frac < 1e-3:
        metric = 1.0 if round(e.beat, 6) in measure_starts else 0.9
    elif abs(frac - 0.5) < 1e-3:
        metric = 0.65
    elif abs(frac - 1 / 3) < 1e-3 or abs(frac - 2 / 3) < 1e-3:
        metric = 0.45
    else:
        metric = 0.35
    mix, drum = feel.accent(tempo.beat_to_ms(e.beat)) if feel is not None else (0.5, 0.5)
    dur = min(e.end_beat - e.beat, 2) / 2
    return 0.3 * metric + 0.25 * mix + 0.15 * drum + 0.2 * min(e.amp, 1) + 0.1 * dur


def _budget(sec: Section, p: MapParams) -> int:
    per_beat = p.notes_per_beat_min + (p.notes_per_beat_max - p.notes_per_beat_min) * sec.energy
    return max(1, int(round(per_beat * (sec.end_beat - sec.start_beat))))


def _groove_fill(picked: list[Event], events: list[Event], sec: Section, trans: Transcription,
                 tempo: TempoMap, feel: Feel, p: MapParams, measure_starts: set[float]) -> list[Event]:
    """Tramo enérgico con pocas notas transcritas (guitarra rítmica distorsionada, palm mute):
    se rellena en tiempos y corcheas con un acento claro de batería o del conjunto, mientras
    la pista suena, repitiendo la nota que esté sonando. Así la chart sigue el groove."""
    budget = _budget(sec, p)
    if sec.energy < p.fill_energy or len(picked) >= p.fill_below * budget:
        return []
    taken = sorted(e.beat for e in picked)
    slots = []
    b = np.ceil(sec.start_beat * 2) / 2
    while b < sec.end_beat - 1e-6:
        t = tempo.beat_to_ms(b)
        f = int(np.searchsorted(trans.frame_times_ms, t))
        sounding = f < len(trans.rms_db) and trans.rms_db[f] > trans.active_db
        mix, drum = feel.accent(t)
        if sounding and max(mix, drum) >= p.fill_accent and all(abs(b - q) >= p.min_gap_weak_beats - 1e-6 for q in taken):
            slots.append((b, mix, drum))
        b += 0.5
    # Nota que suena: la del último evento antes del hueco (o el siguiente si no hay anterior).
    source = sorted(events, key=lambda e: e.beat)
    beats = [e.beat for e in source]
    fills = []
    for b, mix, drum in slots:
        i = int(np.searchsorted(beats, b)) - 1
        ref = source[i] if i >= 0 else (source[0] if source else None)
        if ref is None or abs(ref.beat - b) > p.fill_max_hold_beats:
            continue
        low = min(ref.pitches)
        e = Event(b, b + 0.25, {low: 0.3}, sec.stem)
        e.salience = _salience(e, tempo, feel, measure_starts)
        fills.append(e)
    fills.sort(key=lambda e: e.salience, reverse=True)
    out: list[Event] = []
    for e in fills:
        if len(picked) + len(out) >= budget:
            break
        if all(abs(e.beat - q.beat) >= p.min_gap_weak_beats - 1e-6 for q in out):
            out.append(e)
    return out


def _pick(events: list[Event], sec: Section, tempo: TempoMap, p: MapParams) -> list[Event]:
    """Los eventos del compás que más se sienten, hasta su presupuesto y sin amontonarse."""
    cands = [e for e in events if sec.start_beat <= e.beat < sec.end_beat]
    budget = _budget(sec, p)
    fast = sec.energy >= p.fast_energy
    picked: list[Event] = []
    for e in sorted(cands, key=lambda e: e.salience, reverse=True):
        if len(picked) >= budget:
            break
        too_close = False
        for q in picked:
            gap = p.min_gap_beats if (fast and e.strong and q.strong) else p.min_gap_weak_beats
            gap_ms = abs(tempo.beat_to_ms(e.beat) - tempo.beat_to_ms(q.beat))
            if abs(e.beat - q.beat) < gap - 1e-6 or gap_ms < p.min_gap_ms:
                too_close = True
                break
        if not too_close:
            picked.append(e)
    return picked


def _limit_chords(events: list[Event], sections: list[Section], p: MapParams) -> None:
    """Pocos acordes y en los golpes que más se sienten; de 3 botones solo en tramos muy enérgicos."""
    starts = np.array([s.start_beat for s in sections])

    def energy_at(beat: float) -> float:
        i = int(np.searchsorted(starts, beat, side="right")) - 1
        return sections[i].energy if i >= 0 else p.default_energy

    song_energy = float(np.mean([s.energy for s in sections])) if sections else p.default_energy
    ratio = p.chord_ratio_min + (p.chord_ratio_max - p.chord_ratio_min) * song_energy
    chords = [e for e in events if len(e.pitches) >= 2]
    chords.sort(key=lambda e: e.salience * sorted(e.pitches.values())[-2], reverse=True)
    limit = int(ratio * len(events))
    for i, e in enumerate(chords):
        if i >= limit:
            low = min(e.pitches)
            e.pitches = {low: e.pitches[low]}
        elif len(e.pitches) > 2 and energy_at(e.beat) < p.triad_energy:
            e.pitches = {k: e.pitches[k] for k in sorted(e.pitches)[:2]}


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
                max_size = 1 if e.beat - prev_beat < p.fast_step_beats else 3
                fret = _contour_step(prev_fret, d, target, max_size)

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


def _contour_step(prev_fret: int, d: float, target: int, max_size: int = 3) -> int:
    """Siguiente botón respetando la dirección del intervalo.

    El paso ideal crece con el intervalo (1 botón hasta 4 semitonos, 2 hasta 9,
    3 más allá); entre los botones en esa dirección se elige el que mejor combina
    ese paso con el botón "objetivo" del reparto por orden, para no ir a la deriva
    hacia los extremos.
    """
    direction = 1 if d > 0 else -1
    size = min(max_size, 1 if abs(d) <= 4 else 2 if abs(d) <= 9 else 3)
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
    trans: dict[str, Transcription], tempo: TempoMap, end_beat: float, p: MapParams | None = None,
    feel: Feel | None = None,
) -> tuple[list[ChartNote], list[Section], list[SourceNote]]:
    p = p or MapParams()
    sections = choose_sections(trans, tempo, end_beat, p)
    events = build_events(trans, sections, tempo, p, feel)
    notes = assign_frets(events, tempo, p)
    source = [n for t in trans.values() for n in t.notes]
    return notes, sections, source


def limit_density(notes: list, max_nps: float, window_ms: int = 2000) -> list:
    """Quita las notas menos claras (strength) donde una ventana de window_ms pasa de max_nps por segundo."""
    keep = sorted(notes, key=lambda n: n.start_ms)
    cap = max(1, int(max_nps * window_ms / 1000))
    while len(keep) > cap:
        t = np.array([n.start_ms for n in keep])
        ends = np.searchsorted(t, t + window_ms)
        counts = ends - np.arange(len(t))
        i = int(np.argmax(counts))
        if counts[i] <= cap:
            break
        keep.remove(min(keep[i:ends[i]], key=lambda n: n.strength))
    return keep


def map_from_model(
    trans: dict[str, Transcription], tempo: TempoMap, sections: list[Section],
    model_notes: dict, p: MapParams | None = None,
) -> dict[str, list[ChartNote]]:
    """Charts por dificultad a partir de OnsetNet: el modelo decide cuándo, cuánto dura y si es
    acorde; la transcripción da la altura y los botones salen por contorno.
    Si el modelo predice botones (v4+), se usan los suyos."""
    p = p or MapParams()
    starts = [s.start_beat for s in sections]

    def stem_at(ms: float) -> str:
        i = int(np.searchsorted(starts, tempo.ms_to_beat(ms), side="right")) - 1
        return sections[i].stem if i >= 0 else ""

    out = {}
    for diff, notes in model_notes.items():
        if diff in p.max_nps:
            notes = limit_density(notes, p.max_nps[diff])
        chord_at ={round(quantize(tempo.ms_to_beat(n.start_ms)), 6): n.chord for n in notes}
        events = timed_events([(n.start_ms, n.end_ms) for n in notes], trans, stem_at, tempo)
        if notes and notes[0].frets is not None:
            frets_at = {}
            for n in sorted(notes, key=lambda n: n.strength):  # la más clara manda si dos caen en el mismo pulso
                frets_at[round(quantize(tempo.ms_to_beat(n.start_ms)), 6)] = n.frets
            chart = [ChartNote(tempo.beat_to_ms(e.beat), frets_at[e.beat], beat=e.beat, end_beat=e.end_beat,
                               pitch=int(min(e.pitches)), stem=e.stem) for e in events]
            _sustains_and_hopos(chart, tempo, p)
            out[diff] = chart
            continue
        for e in events:
            e.pitches = _clean_pitches(e.pitches, p.chord_amp_ratio)
            prob = chord_at.get(e.beat, 0.0)
            low = min(e.pitches)
            if prob < 0.5:
                e.pitches = {low: e.pitches[low]}
            elif len(e.pitches) == 1:
                e.pitches = {low: e.pitches[low], low + 7: e.pitches[low]}  # acorde de quinta
        out[diff] = assign_frets(events, tempo, p)
    return out


def timed_events(spans: list[tuple[int, int]], trans: dict[str, Transcription], section_stem_at,
                 tempo: TempoMap) -> list[Event]:
    """Un evento por (inicio, fin) en ms. Altura: la voz si canta justo ahí; si no, la pista del tramo."""
    events: dict[float, Event] = {}
    last_pitch = 52
    for s, e in spans:
        beat = round(quantize(tempo.ms_to_beat(s)), 6)
        end_beat = tempo.ms_to_beat(e)
        pitches = _pitches_at(s, trans.get("vocals"), 120) or _pitches_at(s, trans.get(section_stem_at(s) or "guitar"), 150)
        if not pitches:
            pitches = {last_pitch: 0.5}
        last_pitch = min(pitches)
        ev = Event(beat, end_beat, pitches, "modelo", strong=True)
        ev.salience = 1.0
        if beat not in events or end_beat > events[beat].end_beat:
            events[beat] = ev
    return sorted(events.values(), key=lambda e: e.beat)


def _pitches_at(t: float, trans: Transcription | None, window_ms: int) -> dict[int, float]:
    if trans is None:
        return {}
    near = [n for n in trans.notes if abs(n.start_ms - t) <= window_ms and n.amp >= 0.3]
    if not near:
        near = [n for n in trans.notes if n.start_ms <= t < n.end_ms and n.amp >= 0.3]
    if not near:
        return {}
    best_start = min(near, key=lambda n: abs(n.start_ms - t)).start_ms
    return {n.pitch: n.amp for n in near if abs(n.start_ms - best_start) <= 40}
