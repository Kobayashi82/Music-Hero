"""Biblioteca (artista -> álbum -> canción) y menús largos. uv run --project app --with pytest pytest app/tests"""

import json

from app.library import NO_ALBUM, group, scan, search, split_prefix
from app.menu import PAGE, WINDOW, Menu, Option, SearchMenu


def make_song(tmp, charts, rel: str, title: str, artist: str = "", album: str = "", sha: str = "") -> None:
    audio = tmp / "Musicas" / rel
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"")
    folder = charts / (audio.stem + sha)
    folder.mkdir(parents=True)
    song = {"title": title, "artist": artist, "album": album, "duration_ms": 200000,
            "audio_sha256": sha or audio.stem, "audio_file": str(audio)}
    (folder / "chart.json").write_text(json.dumps({"song": song}), encoding="utf-8")


def test_agrupa_por_carpetas_y_ordena_por_prefijos(tmp_path):
    charts = tmp_path / "charts"
    make_song(tmp_path, charts, "Queen/Greatest Hits II/Queen - Hammer to Fall.mp3", "Hammer to Fall", "Queen")
    make_song(tmp_path, charts, "Queen/Greatest Hits III/Under Pressure.mp3", "Under Pressure", "Queen & David Bowie")
    make_song(tmp_path, charts, "Avril Lavigne/2 - Under My Skin/01 - Take Me Away.mp3", "Take Me Away", "Avril")
    make_song(tmp_path, charts, "Avril Lavigne/1 - Let Go/02 - Complicated.mp3", "Complicated", "Avril")
    make_song(tmp_path, charts, "Avril Lavigne/1 - Let Go/01 - Losing Grip.mp3", "Losing Grip", "Avril")
    make_song(tmp_path, charts, "AI Music/suelta.mp3", "Suelta", "AI")
    cache = tmp_path / "library.json"
    entries = scan(charts, cache)
    assert len(entries) == 6 and cache.exists()
    assert len(scan(charts, cache)) == 6  # con la caché, lo mismo
    tree = group(entries)
    assert list(tree) == ["AI Music", "Avril Lavigne", "Queen"]
    assert list(tree["Avril Lavigne"]) == ["Let Go", "Under My Skin"]  # por el prefijo, sin él en el nombre
    assert [e.title for e in tree["Avril Lavigne"]["Let Go"]] == ["Losing Grip", "Complicated"]
    assert set(tree["Queen"]) == {"Greatest Hits II", "Greatest Hits III"}  # el dúo sigue en Queen
    assert list(tree["AI Music"]) == [NO_ALBUM]


def test_sin_audio_no_sale(tmp_path):
    charts = tmp_path / "charts"
    make_song(tmp_path, charts, "X/Y/z.mp3", "Z")
    (tmp_path / "Musicas" / "X" / "Y" / "z.mp3").unlink()
    assert scan(charts, tmp_path / "library.json") == []


def test_prefijos():
    assert split_prefix("02 - Complicated") == (2, "Complicated")
    assert split_prefix("1 - Let Go") == (1, "Let Go")
    assert split_prefix("Queen - Hammer to Fall") == (None, "Queen - Hammer to Fall")


def test_menu_largo_en_ventana():
    m = Menu("t", [Option(str(i), value=str(i * 2)) for i in range(40)])
    assert len(m.view()["items"]) == WINDOW
    m.page(1)
    m.page(1)
    assert m.sel == 2 * PAGE
    v = m.view()
    assert v["items"][v["sel"]] == str(2 * PAGE) and v["position"] == "21 / 40"
    assert v["values"][v["sel"]] == str(4 * PAGE)  # valor fijo (texto)


def test_menu_largo_circular():
    m = Menu("t", [Option(str(i)) for i in range(40)])
    v = m.view()
    assert v["sel"] == WINDOW // 2 and v["items"][v["sel"]] == "0" and v["above"] and v["below"]
    assert v["items"][0] == str(40 - WINDOW // 2)  # por encima de la primera, las últimas
    assert v["wrap"] == WINDOW // 2  # y ahí vuelve a empezar
    m.move(-1)
    assert m.sel == 39 and m.view()["items"][WINDOW // 2 + 1] == "0"
    m.page(1)
    assert m.sel == PAGE - 1  # el salto también da la vuelta
    m.page(-1)
    assert m.sel == 39
    assert Menu("t", [Option(str(i)) for i in range(5)]).view()["wrap"] == -1  # las cortas, como siempre


def test_buscar(tmp_path):
    charts = tmp_path / "charts"
    make_song(tmp_path, charts, "Queen/Greatest Hits II/Queen - Hammer to Fall.mp3", "Hammer to Fall", "Queen")
    make_song(tmp_path, charts, "Queen/Greatest Hits III/Under Pressure.mp3", "Under Pressure", "Queen & David Bowie")
    make_song(tmp_path, charts, "Avril Lavigne/1 - Let Go/02 - Complicated.mp3", "Complicated", "Avril")
    make_song(tmp_path, charts, "Rosalía/El Mal Querer/Malamente.mp3", "Malamente", "Rosalía")
    entries = scan(charts, tmp_path / "library.json")
    group(entries)
    titles = lambda q: [e.title for e in search(entries, q)]  # noqa: E731
    assert titles("under") == ["Under Pressure"]
    assert titles("queen") == ["Hammer to Fall", "Under Pressure"]  # por artista
    assert titles("bowie press") == ["Under Pressure"]  # todas las palabras, en cualquier campo
    assert titles("ROSALIA") == ["Malamente"]  # sin tildes ni mayúsculas
    assert titles("let go") == ["Complicated"]  # por álbum
    assert titles("  ") == [] and titles("zzz") == []


def test_menu_de_busqueda():
    songs = ["Hammer to Fall", "Under Pressure", "Complicated"]
    picked = []
    m = SearchMenu("Buscar", lambda q: [Option(s, lambda s=s: picked.append(s)) for s in songs if q in s.lower()])
    assert len(m.options) == SearchMenu.FIXED
    m.type("u")  # teclado: queda elegido el primer resultado
    assert m.query == "u" and m.sel == SearchMenu.FIXED and m.options[m.sel].label == "Under Pressure"
    m.select()
    assert picked == ["Under Pressure"]
    m.backspace()
    m.sel = 0
    m.select()  # guitarra: «Escribir» se edita, el strum elige la letra y verde la añade
    assert m.editing
    m.move(1)  # strum abajo: la letra anterior (de la «a» da la vuelta al espacio)
    m.move(-1), m.move(-1), m.move(-1)  # arriba: a, b, c
    m.select()
    assert m.query == "c" and m.editing and [o.label for o in m.options[SearchMenu.FIXED:]] == ["Complicated"]
    assert m.back() and not m.editing
    m.sel = 1
    m.select()  # «Borrar letra»
    assert m.query == "" and "Buscar:" in m.body
