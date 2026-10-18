"""Letra en el juego: qué línea se ve y cuánto va iluminado. uv run --project app --with pytest pytest app/tests"""

import json

import pytest

from app.lyrics import HOLD_MS, SHOW_BEFORE_MS, Lyrics

SHA = "cd" * 32


def line(start, words):
    """words: [(texto, duración ms)] seguidas desde start."""
    out, t = [], start
    for text, dur in words:
        out.append({"start_ms": t, "end_ms": t + dur, "text": text})
        t += dur
    return {"start_ms": start, "end_ms": t, "text": "".join(w["text"] for w in out).strip(), "words": out}


def write(tmp_path, lines, sha=SHA):
    (tmp_path / "lyrics.json").write_text(json.dumps({"schema_version": 1, "audio_sha256": sha, "lines": lines}),
                                          encoding="utf-8")
    return tmp_path


@pytest.fixture
def lyrics(tmp_path):
    return Lyrics.load(write(tmp_path, [
        line(10000, [(" Hello", 500), (" world", 500)]),  # 10.0 - 11.0
        line(11500, [(" second", 1000)]),  # 11.5 - 12.5
        line(40000, [("曇", 300), ("天", 300)]),  # tras una pausa larga
    ]), SHA)


def test_fill_goes_word_by_word(lyrics):
    v = lyrics.view(10000 - SHOW_BEFORE_MS + 10)
    assert v["current"] == "Hello world" and v["fill"] == 0 and v["next"] == "second"
    assert lyrics.view(10250)["fill"] == pytest.approx(2.5)  # mitad de "Hello"
    assert lyrics.view(10499)["fill"] == pytest.approx(5, abs=0.02)
    assert lyrics.view(10500)["fill"] == 6  # empieza "world": el espacio ya pasó
    assert lyrics.view(11000)["fill"] == 11


def test_current_line_keeps_its_place_until_sung(lyrics):
    assert lyrics.view(10900)["current"] == "Hello world"  # "second" ya entraría, pero esta sigue
    assert lyrics.view(11200)["current"] == "second"
    assert lyrics.view(12500 + HOLD_MS - 10)["current"] == "second"
    assert lyrics.view(12500 + HOLD_MS - 10)["next"] == ""  # la siguiente está lejos


def test_long_pause_shows_nothing_then_next_line(lyrics):
    assert lyrics.view(20000)["current"] == ""
    assert lyrics.view(5000)["current"] == ""
    v = lyrics.view(40000 - SHOW_BEFORE_MS + 1)
    assert v["current"] == "曇天" and v["fill"] == 0
    assert lyrics.view(40450)["fill"] == pytest.approx(1.5)
    assert lyrics.view(99999)["current"] == ""


def test_load_rejects_other_audio_and_broken_files(tmp_path):
    write(tmp_path, [line(0, [(" a", 100)])], sha="ef" * 32)
    assert Lyrics.load(tmp_path, SHA) is None
    write(tmp_path, [])
    assert Lyrics.load(tmp_path, SHA) is None  # instrumental: nada que enseñar
    (tmp_path / "lyrics.json").write_text("{roto", encoding="utf-8")
    assert Lyrics.load(tmp_path, SHA) is None
    (tmp_path / "lyrics.json").unlink()
    assert Lyrics.load(tmp_path, SHA) is None
