"""Biblioteca (artista -> álbum -> canción) y menús largos. uv run --project app --with pytest pytest app/tests"""

import json

from app.library import NO_ALBUM, group, scan, search, split_prefix
from app.menu import WINDOW, Menu, Option, SearchMenu


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


def test_menu_largo_por_paginas():
    m = Menu("t", [Option(str(i), value=str(i * 2)) for i in range(40)])  # páginas de 11: 0-10 ... 33-39
    v = m.view()
    assert v["items"][0] == "0" and v["sel"] == 0 and not v["above"] and v["below"]
    for _ in range(WINDOW - 1):
        m.move(1)
    assert m.view()["items"][0] == "0" and m.view()["sel"] == WINDOW - 1  # la página quieta, baja la selección
    m.move(1)
    v = m.view()
    assert v["items"][0] == str(WINDOW) and v["sel"] == 0 and v["above"]  # página siguiente, arriba
    assert v["values"][0] == str(2 * WINDOW) and v["position"] == "12 / 40 · página 2 de 4"
    m.page(1), m.page(1)
    v = m.view()  # última página: 33-39 y cuatro filas vacías (mismo alto)
    assert m.sel == 39 - 6 and len(v["items"]) == WINDOW and v["items"][-1] == "" and v["rows"][-1] == -1
    m.sel = 39
    m.move(1)
    assert m.sel == 0 and m.view()["items"][0] == "0"  # tras la última, la primera página
    m.move(-1)
    assert m.sel == 39 and m.view()["items"][0] == "33"
    m.sel = 9
    m.page(-1)  # de la primera a la última, en la misma fila o la última que haya
    assert m.sel == 39
    assert len(Menu("t", [Option(str(i)) for i in range(5)]).view()["items"]) == 5  # las cortas, sin relleno


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


def test_carpetas_de_musica_y_las_que_no_tienen_chart(tmp_path):
    from app.library import MusicWatcher, find_music, in_dirs, pending_entries, without_chart

    charts = tmp_path / "charts"
    make_song(tmp_path, charts, "Queen/Greatest Hits II/Queen - Hammer to Fall.mp3", "Hammer to Fall", "Queen")
    make_song(tmp_path, charts, "Avril Lavigne/Let Go/Losing Grip.mp3", "Losing Grip", "Avril")
    nueva = tmp_path / "Musicas" / "Queen" / "Greatest Hits II" / "02 - Nueva.flac"
    nueva.write_bytes(b"")
    (tmp_path / "Musicas" / "Queen" / "portada.jpg").write_bytes(b"")
    music_dir = str(tmp_path / "Musicas")
    music = find_music([music_dir, music_dir])  # repetida: sin duplicados
    assert len(music) == 3 and all(m.endswith((".mp3", ".flac")) for m in music)
    missing = without_chart(music, scan(charts, tmp_path / "library.json"))
    assert missing == [str(nueva)]
    assert in_dirs(str(nueva), [music_dir]) and not in_dirs(str(nueva), [str(tmp_path / "Otra")])
    assert not in_dirs(music_dir + "2/x.mp3", [music_dir])  # «Musicas2» no está dentro de «Musicas»
    tree = group(scan(charts, tmp_path / "library.json") + pending_entries(missing))
    songs = tree["Queen"]["Greatest Hits II"]
    assert [(e.title, bool(e.folder)) for e in songs] == [("Nueva", False), ("Hammer to Fall", True)]

    w = MusicWatcher(interval_s=3600)
    w.set_dirs([music_dir])
    import time
    for _ in range(100):
        found = w.take()
        if found is not None:
            break
        time.sleep(0.02)
    assert found == music
