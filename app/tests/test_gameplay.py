"""Reglas del juego. uv run --project app --with pytest pytest app/tests"""

from app.chart import Note
from app.gameplay import HIT, MISSED, Game


def play(game: Game, frets: list[int], t: float) -> None:
    for f in list(game.held):
        if f not in frets:
            game.fret(f, False, t)
    for f in frets:
        if f not in game.held:
            game.fret(f, True, t)
    game.strum(t)


def test_hit_dentro_de_la_ventana_y_fallo_fuera():
    g = Game([Note(1000, (0,)), Note(2000, (1,))])
    play(g, [0], 1050)
    assert g.notes[0].state == HIT and g.stats.streak == 1
    g.update(2100)
    assert g.notes[1].state == MISSED and g.stats.streak == 0 and g.stats.misses == 1


def test_anclaje_en_notas_sueltas_y_acordes_exactos():
    g = Game([Note(1000, (2,)), Note(2000, (0, 2))])
    play(g, [0, 1, 2], 1000)  # verde y rojo anclados bajo el amarillo
    assert g.notes[0].state == HIT
    play(g, [0, 1, 2], 2000)  # acorde verde+amarillo con el rojo de más
    assert g.notes[1].state != HIT and g.stats.overstrums == 1
    play(g, [0, 2], 2020)
    assert g.notes[1].state == HIT


def test_traste_mas_alto_equivocado():
    g = Game([Note(1000, (1,))])
    play(g, [3], 1000)
    assert g.notes[0].state != HIT and g.stats.overstrums == 1


def test_strum_sin_nota_rompe_la_racha():
    g = Game([Note(1000, (0,)), Note(3000, (0,))])
    play(g, [0], 1000)
    g.strum(2000)
    assert g.stats.streak == 0 and g.stats.overstrums == 1


def test_hopo_sin_strum_solo_con_racha():
    g = Game([Note(1000, (0,)), Note(1100, (1,), hopo=True), Note(1200, (2,), hopo=True)])
    play(g, [0], 1000)
    g.fret(1, True, 1100)  # cambia a rojo sin strum
    assert g.notes[1].state == HIT
    g.strum(1110)  # strum de cortesía: no cuenta como de más
    assert g.stats.overstrums == 0 and g.stats.streak == 2
    g.fret(2, True, 1200)
    assert g.notes[2].state == HIT and g.stats.streak == 3

    g2 = Game([Note(1000, (1,), hopo=True)])
    g2.fret(1, True, 1000)  # sin racha, un HOPO necesita strum
    assert g2.notes[0].state != HIT


def test_multiplicador_y_puntos():
    g = Game([Note(1000 + 200 * i, (0,)) for i in range(12)] + [Note(5000, (0, 1))])
    for i in range(12):
        play(g, [0], 1000 + 200 * i)
    assert g.stats.multiplier == 2
    play(g, [0, 1], 5000)
    assert g.stats.score == 10 * 50 + 2 * 50 * 2 + 2 * 50 * 2  # 10 a x1, 2 a x2, acorde de 2 a x2


def test_sustain_suma_mientras_se_mantiene():
    g = Game([Note(1000, (0,), sustain_ms=1000)])
    play(g, [0], 1000)
    base = g.stats.score
    g.update(1500)
    mid = g.stats.score
    assert mid > base
    g.fret(0, False, 1600)
    g.update(2000)
    assert g.stats.score == mid + 100 * 25 / 500  # hasta los 1600 ms, no más
    assert g.finished


def test_tocar_una_posterior_marca_las_anteriores_como_fallo():
    g = Game([Note(1000, (0,)), Note(1050, (1,))])
    play(g, [1], 1060)
    assert g.notes[0].state == MISSED and g.notes[1].state == HIT and g.stats.streak == 1
