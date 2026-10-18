"""Star power: frases, barra, multiplicador y guitarra levantada. uv run --project app --with pytest pytest app/tests"""

from app.chart import Note
from app.gameplay import Game
from app.starpower import BeatClock, Tilt, phrases

BEATS = list(range(0, 120000, 500))  # 120 ppm


def hit(g: Game, note: Note) -> None:
    for f in list(g.held):
        g.fret(f, False, note.time_ms)
    for f in note.frets:
        g.fret(f, True, note.time_ms)
    g.strum(note.time_ms)


def test_frase_completa_llena_un_cuarto_y_fallar_la_apaga():
    notes = [Note(1000 + 250 * i, (i % 5,)) for i in range(16)]  # 1000..4750
    g = Game(notes, phrases=[(1000, 2000), (3000, 4000)], beats=BEATS)
    assert [g.is_star(ns) for ns in g.notes[:5]] == [True] * 4 + [False]
    for n in notes[:8]:
        hit(g, n)
    assert g.energy == 0.25 and g.stats.phrases == 1 and ("phrase", 1750, g.notes[3]) in g.events
    hit(g, notes[8])  # 3000: primera de la segunda frase
    g.update(3250 + 200)  # la de 3250 pasa sin tocar
    assert not g.is_star(g.notes[9]) and not g.is_star(g.notes[10])
    for n in notes[10:]:
        hit(g, n)
    assert g.energy == 0.25 and g.stats.phrases == 1


def test_activar_dobla_el_multiplicador_y_se_gasta_en_32_pulsos():
    notes = [Note(1000 + 100 * i, (0,)) for i in range(8)] + [Note(20000, (0,))]
    g = Game(notes, phrases=[(1000, 1400), (1400, 1800)], beats=BEATS)
    assert not g.activate(500)  # sin barra
    for n in notes[:8]:
        hit(g, n)
    assert g.energy == 0.5 and g.star_ready
    assert g.activate(2000)
    assert g.stats.star and g.stats.multiplier == 2 * g.stats.base_multiplier
    g.update(2000 + 8 * 500)  # 8 pulsos: un cuarto
    assert abs(g.energy - 0.25) < 1e-9 and g.stats.star
    g.update(2000 + 16 * 500)
    assert g.energy == 0 and not g.stats.star and g.stats.multiplier == g.stats.base_multiplier
    assert any(k == "star_end" for k, _, _ in g.events)


def test_multiplicador_hasta_x8():
    notes = [Note(1000 + 100 * i, (0,)) for i in range(40)]
    g = Game(notes, phrases=[(1000, 1200), (1200, 1400)], beats=BEATS)
    for n in notes[:4]:
        hit(g, n)
    g.activate(1400)
    for n in notes[4:35]:
        hit(g, n)
    assert g.stats.base_multiplier == 4 and g.stats.multiplier == 8


def test_empezar_a_mitad_de_una_frase_no_la_completa():
    notes = [Note(1000 + 100 * i, (0,)) for i in range(6)]
    g = Game(notes, phrases=[(1000, 1600)], beats=BEATS)
    g.skip_to(1150)
    for n in notes[2:]:
        hit(g, n)
    assert g.energy == 0 and not g.is_star(g.notes[3])


def test_frases_cada_20_30_s_en_los_tramos_densos():
    beats = [(t, (t // 500) % 4 == 0) for t in range(0, 180000, 500)]
    notes = [Note(t, (0,)) for t in range(2000, 178000, 1000)]  # una por segundo...
    notes += [Note(t, (1,)) for t in range(30000, 34000, 125)]  # ...y un tramo muy denso a los 30 s
    notes.sort(key=lambda n: n.time_ms)
    ph = phrases(notes, beats)
    assert len(ph) >= 5
    assert all(e - s == 4000 for s, e in ph)  # 2 compases de 4 pulsos a 120 ppm
    assert (30000, 34000) in ph  # el más denso de los que caen 15-25 s tras la primera
    for (_, e0), (s1, _) in zip(ph, ph[1:]):
        assert 15000 <= s1 - e0 <= 25000
    assert phrases([], beats) == []


def test_reloj_de_pulsos():
    c = BeatClock([1000, 1500, 2000, 3000])
    assert c.pos(1000) == 0 and c.pos(1250) == 0.5 and c.pos(2500) == 2.5 and c.pos(4000) == 4
    assert BeatClock([]).pos(1000) == 2  # sin pulsos: 120 ppm


def test_levantar_el_mastil():
    # valores de tools/poc_wii_tilt.py con la guitarra de Wii del usuario (x, y, z en g)
    normal, tilted, up = (0.15, -0.08, 1.02), (0.52, -0.38, 0.81), (-0.08, -1.0, 0.15)
    t = Tilt()
    assert not any(t.feed(normal) for _ in range(50))
    assert not any(t.feed(tilted) for _ in range(200))  # algo inclinada tocando: no
    assert t.feed((0.7, -0.35, 1.0)) is False  # un golpe suelto tampoco
    fired = [t.feed(up) for _ in range(30)]
    assert fired.count(True) == 1 and fired.index(True) < 12  # una vez, en ~100 ms
    assert not any(t.feed(up) for _ in range(50))  # sigue levantada: nada más
    for _ in range(30):
        t.feed(normal)
    assert any(t.feed(up) for _ in range(30))  # bajada y otra vez arriba: otra
    assert not Tilt().feed((0.0, 0.0, 0.0))  # informes sin acelerómetro
