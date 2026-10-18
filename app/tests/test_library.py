"""Biblioteca (artista -> álbum -> canción) y menús largos. uv run --project app --with pytest pytest app/tests"""

import json

from app.library import NO_ALBUM, group, scan, split_prefix
from app.menu import PAGE, WINDOW, Menu, Option


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
    v = m.view()
    assert len(v["items"]) == WINDOW and not v["above"] and v["below"] and v["sel"] == 0
    m.page(1)
    m.page(1)
    assert m.sel == 2 * PAGE
    v = m.view()
    assert v["items"][v["sel"]] == str(2 * PAGE) and v["above"] and v["below"] and v["position"] == "21 / 40"
    assert v["values"][v["sel"]] == str(4 * PAGE)  # valor fijo (texto)
    m.page(1), m.page(1), m.page(1)
    assert m.sel == 39 and not m.view()["below"]  # el salto no da la vuelta
    m.move(1)
    assert m.sel == 0  # el strum sí
