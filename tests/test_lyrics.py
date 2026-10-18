"""Letra sincronizada (generator.lyrics), sin GPU ni red: Whisper y LRCLIB simulados."""

import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from generator import lyrics as L

ROOT = Path(__file__).resolve().parents[1]
SHA = "ab" * 32


def word(text, start, end, p=0.9):
    return SimpleNamespace(word=text, start=start, end=end, probability=p)


def result(*segs):
    return SimpleNamespace(segments=[SimpleNamespace(words=list(ws)) for ws in segs])


def w(text, start, end):
    return {"start_ms": start, "end_ms": end, "text": text}


def test_lyric_lines_drops_tags_and_symbols():
    text = "[Chorus]\nHello there\n\n♪\n(Verso 2)\nOtra línea\n"
    assert L.lyric_lines(text) == ["Hello there", "(Verso 2)", "Otra línea"]
    assert L.lyric_lines("[Intro]\n(coro)\n") == []


def test_clean_title():
    assert L._clean_title("Gosia (Mokum Sessions)") == "Gosia"
    assert L._clean_title("Song - Remastered 2011") == "Song"


def test_get_retries_server_errors(monkeypatch):
    calls = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": 1}'

    def urlopen(req, timeout):
        calls.append(req.full_url)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
        return Resp()

    monkeypatch.setattr(L.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    assert L._get("https://lrclib.net/api/x") == {"ok": 1}
    assert len(calls) == 3

    def not_found(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "no", {}, None)

    monkeypatch.setattr(L.urllib.request, "urlopen", not_found)
    assert L._get("https://lrclib.net/api/x") is None


def test_fetch_lrclib_prefers_same_duration_then_same_song(monkeypatch):
    other = {"id": 1, "artistName": "Necry Talkie", "trackName": "Kininatteiku", "duration": 218, "plainLyrics": "a"}
    close = dict(other, id=2, duration=272)
    stranger = dict(other, id=3, artistName="Someone Else", duration=100)
    found = [other, stranger]
    monkeypatch.setattr(L, "_get", lambda url: None if "/get?" in url else list(found))
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    rec = L.fetch_lrclib("Kininatteiku", "Necry Talkie", "Freak", 274)
    assert rec["id"] == 1 and rec["duration_mismatch"]
    found.append(close)
    rec = L.fetch_lrclib("Kininatteiku", "Necry Talkie", "Freak", 274)
    assert rec["id"] == 2 and "duration_mismatch" not in rec
    found[:] = [stranger]
    assert L.fetch_lrclib("Kininatteiku", "Necry Talkie", "Freak", 274) is None


def test_short_words_are_spread():
    words = [w(" a", 1000, 1000), w(" b", 1000, 1000), w(" c", 1000, 1600), w(" d", 2000, 2000)]
    L._fix_short_words(words)
    assert all(x["end_ms"] - x["start_ms"] >= L.MIN_WORD_MS for x in words)
    assert [x["start_ms"] for x in words] == sorted(x["start_ms"] for x in words)
    assert words[2]["end_ms"] <= 1600


def test_split_long_line_at_pause():
    words = [w(f" w{i}", i * 400, i * 400 + 300) for i in range(10)]
    words += [w(f" v{i}", 9000 + i * 400, 9300 + i * 400) for i in range(10)]
    lines = L.split_line(words)
    assert len(lines) == 2 and lines[1]["words"][0]["text"] == " v0"
    assert lines[0]["text"] == "w0 w1 w2 w3 w4 w5 w6 w7 w8 w9"
    short = [w(" hi", 0, 200), w(" there", 200, 9000)]  # la última se alarga: no se parte
    assert len(L.split_line(short)) == 1


def test_split_japanese_avoids_middle_of_katakana():
    text = "シャンプーハットをかぶったようなそんな感覚だった今夜しつこく踊ろう"
    words = [w(c, i * 300, i * 300 + 250) for i, c in enumerate(text)]
    lines = L.split_line(words)
    assert len(lines) >= 2
    for a, b in zip(lines, lines[1:]):
        assert L._cjk_cut(a["text"], b["text"]) >= 0, (a["text"], b["text"])


def test_transcription_filters_ghosts_and_collapsed_lines():
    res = result([word(" Hello", 1.0, 1.4), word(" world", 1.5, 2.0)],
                 [word(" Thanks", 3.0, 3.2), word(" for", 3.2, 3.4), word(" watching", 3.4, 3.9)],
                 [word(" mumble", 5.0, 5.5, p=0.2), word(" mumble", 5.5, 6.0, p=0.2)],
                 [word(" all", 7.0, 7.0), word(" at", 7.0, 7.0), word(" once", 7.0, 7.0)],
                 [word(" Bye", 8.0, 8.5)])
    lines, conf = L._lines_of(res, L.MIN_WHISPER_PROB)
    assert [line["text"] for line in lines] == ["Hello world", "Bye"]
    assert conf == pytest.approx(0.9)
    lines, _ = L._lines_of(res)  # ajuste de texto bueno: no se filtra por confianza ni fantasmas
    assert "Thanks for watching" in [line["text"] for line in lines]


def test_merge_takes_text_from_lrclib_and_times_from_transcript():
    segs = [[w(" Helo", 1000, 1400), w(" wurld", 1500, 2000)],  # mal oído
            [w(" an", 5000, 5200), w(" other", 5200, 5600), w(" line", 5700, 6000)]]
    lines, matched = L.merge_with_transcript(["Hello world", "Another line", "Never sung at all"], segs)
    assert matched > 0.5
    assert ["".join(t["text"] for t in line).strip() for line in lines] == ["Hello world", "Another line"]
    assert 900 <= lines[0][0]["start_ms"] <= 1100 and lines[1][-1]["end_ms"] <= 6000
    assert lines[1][0]["start_ms"] >= 5000


def test_merge_ignores_stray_far_matches():
    segs = [[w("の", 300, 400), w("ら", 500, 600)],  # presentación hablada
            [w(c, 30000 + i * 200, 30180 + i * 200) for i, c in enumerate("窓からしかめっ面のぞかせ")]]
    lines, _ = L.merge_with_transcript(["曇天の午後なら窓からしかめっ面覗かせ"], segs)
    assert len(lines) == 1 and lines[0][0]["start_ms"] >= 25000


def make_folder(tmp_path):
    folder = tmp_path / "Song"
    (folder / "stems").mkdir(parents=True)
    (folder / "stems" / "vocals.flac").write_bytes(b"")
    song = {"title": "Song", "artist": "Band", "album": "Album", "duration_ms": 200000, "audio_sha256": SHA}
    (folder / "chart.json").write_text(json.dumps({"song": song}), encoding="utf-8")
    return folder


class FakeModel:
    def __init__(self, align_prob=0.9):
        self.align_prob = align_prob
        self.transcribed = False

    def align(self, audio, text, language, original_split):
        segs = [[word(" " + t, 1.0 + i * 3 + j * 0.4, 1.3 + i * 3 + j * 0.4, self.align_prob)
                 for j, t in enumerate(line.split())] for i, line in enumerate(text.split("\n"))]
        return result(*segs)

    def transcribe(self, audio, language, verbose):
        self.transcribed = True
        return result(*[[word(" hello", 10.0 + i * 2, 10.4 + i * 2), word(f" world{i}", 10.5 + i * 2, 11.0 + i * 2)]
                        for i in range(15)])


@pytest.fixture
def schema():
    jsonschema = pytest.importorskip("jsonschema")
    s = json.loads((ROOT / "shared" / "lyrics_schema.json").read_text(encoding="utf-8"))
    return lambda d: jsonschema.validate(d, s)


@pytest.mark.parametrize("rec, align_prob, source", [
    ({"id": 7, "plainLyrics": "Hello world\nSecond line here"}, 0.9, "lrclib"),
    ({"id": 7, "plainLyrics": "Hello world\nSecond line here", "duration_mismatch": True}, 0.1, "lrclib+whisper"),
    ({"id": 7, "plainLyrics": "Nothing alike in the text\nreally"} | {"duration_mismatch": True}, 0.1, "whisper"),
    (None, 0.9, "whisper"),
    ({"id": 7, "instrumental": True}, 0.9, "instrumental"),
])
def test_lyrics_for_writes_valid_json_and_caches(tmp_path, monkeypatch, schema, rec, align_prob, source):
    folder = make_folder(tmp_path)
    model = FakeModel(align_prob)
    monkeypatch.setattr(L, "fetch_lrclib", lambda *a: rec)
    monkeypatch.setattr(L, "load_model", lambda device: model)
    monkeypatch.setattr(L, "detect_language", lambda m, v: "en")
    d = L.lyrics_for(folder, "cpu")
    assert d["source"] == source
    on_disk = json.loads((folder / "lyrics.json").read_text(encoding="utf-8"))
    schema(on_disk)
    for line in on_disk["lines"]:
        assert "".join(x["text"] for x in line["words"]).strip() == line["text"]
    starts = [x["start_ms"] for line in on_disk["lines"] for x in line["words"]]
    assert starts == sorted(starts)
    assert L.lyrics_for(folder, "cpu") is None  # ya hecha
    assert L.lyrics_for(folder, "cpu", force=True) is not None


def test_chart_folders(tmp_path):
    a = make_folder(tmp_path)
    assert L.chart_folders([a]) == [a]
    assert L.chart_folders([tmp_path]) == [a]
    assert L.chart_folders([], charts_dir=tmp_path) == [a]
