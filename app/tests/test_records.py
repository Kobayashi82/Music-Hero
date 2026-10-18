"""Récords y dificultad por canción. uv run --project app --with pytest pytest app/tests"""

from datetime import datetime

from app.records import HISTORY, Play, Records


def play(score: int, acc: float = 0.9, streak: int = 10) -> Play:
    return Play(score, acc, 90, 100, streak, 2)


def test_primera_partida_mejor_y_peor(tmp_path):
    r = Records(tmp_path / "stats.json")
    assert r.best("abc", "hard") is None
    first = r.add_play("abc", "hard", play(1000), "Canción", "Grupo", datetime(2026, 10, 18, 20, 0))
    assert first is not None and first.score == 0  # primera: récord sin anterior
    assert r.add_play("abc", "hard", play(800, acc=0.95, streak=30)) is None  # no lo supera
    prev = r.add_play("abc", "hard", play(1500))
    assert prev.score == 1000 and prev.date == "2026-10-18T20:00:00"
    st = r.stats("abc", "hard")
    assert st["plays"] == 3 and st["best"]["score"] == 1500
    assert st["best_accuracy"] == 0.95 and st["best_streak"] == 30  # cada máximo por su lado
    assert r.best("abc", "expert") is None  # cada dificultad aparte


def test_se_guarda_en_disco_y_el_historial_tiene_tope(tmp_path):
    path = tmp_path / "stats.json"
    r = Records(path)
    for i in range(HISTORY + 5):
        r.add_play("abc", "easy", play(i))
    r.set_difficulty("abc", "medium", "Canción", "Grupo")
    r2 = Records(path)
    assert len(r2.stats("abc", "easy")["history"]) == HISTORY
    assert r2.difficulty("abc") == "medium" and r2.difficulty("otra") is None
    assert r2.data["songs"]["abc"]["title"] == "Canción"


def test_sin_fallos():
    assert Play(1, 1.0, 50, 50, 50, 0).full_combo
    assert not Play(1, 0.98, 49, 50, 40, 0).full_combo
