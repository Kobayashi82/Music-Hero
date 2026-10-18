"""Menús, calibración y cambio de dificultad a mitad. uv run --project app --with pytest pytest app/tests"""

import numpy as np

from app import calibration
from app.chart import Note
from app.gameplay import HIT, SKIPPED, Game
from app.menu import Menu, Option, cycler, stepper


def test_mover_elegir_y_editar():
    picked = []
    box = {"v": 1.0}
    m = Menu("t", [Option("a", lambda: picked.append("a")),
                   Option("v", value=lambda: str(box["v"]),
                          change=stepper(lambda: box["v"], lambda x: box.update(v=x), 0.1, 0.5, 1.2))])
    m.move(-1)  # strum arriba desde la primera: da la vuelta a la última
    assert m.sel == 1
    m.select()
    assert m.editing
    m.move(-1)  # editando, arriba sube
    m.move(-1)
    m.move(-1)
    assert box["v"] == 1.2  # con tope
    m.move(1)
    assert box["v"] == 1.1
    assert m.back() and not m.editing  # volver deja de editar
    assert not m.back()  # y otra vez ya es cerrar el menú
    m.move(1)
    m.select()
    assert picked == ["a"]
    assert m.view()["values"] == ["", "1.1"]


def test_cycler_no_da_la_vuelta():
    box = {"d": "easy"}
    ch = cycler(["easy", "medium", "hard"], lambda: box["d"], lambda v: box.update(d=v))
    ch(-1)
    assert box["d"] == "easy"
    ch(1), ch(1), ch(1)
    assert box["d"] == "hard"


def test_calibracion_mide_el_retardo():
    clicks = calibration.click_times_ms()
    rng = np.random.default_rng(0)
    strums = [c + 60 + rng.normal(0, 10) for c in clicks[calibration.COUNT_IN:]]
    med, n, spread = calibration.measure(strums + [clicks[0] + 5, 99999])
    assert abs(med - 60) < 8 and n == calibration.CLICKS and spread < 15
    assert calibration.measure(strums[:3]) is None
    track = calibration.click_track(48000)
    assert track.shape[1] == 2 and np.abs(track).max() > 0.3


def test_skip_to_no_cuenta_las_notas_pasadas():
    g = Game([Note(1000, (0,)), Note(2000, (1,)), Note(3000, (2,))])
    g.skip_to(2500)
    assert [ns.state for ns in g.notes[:2]] == [SKIPPED, SKIPPED]
    g.update(2900)
    assert g.stats.misses == 0
    g.fret(2, True, 3000)
    g.strum(3000)
    assert g.notes[2].state == HIT and g.stats.accuracy == 1.0
