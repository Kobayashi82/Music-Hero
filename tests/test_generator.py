"""Tests del generador que no necesitan GPU ni audio.

    uv run --project generator --with pytest pytest tests
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from generator.export_chart import RESOLUTION, chart_json, write_clonehero
from generator.mapping import MapParams, _contour_step, _rank_fret, map_expert
from generator.model import SongInfo, SourceNote
from generator.rhythm import TempoMap, quantize

ROOT = Path(__file__).resolve().parents[1]


def tempo_120(n_beats: int = 200, first_ms: int = 500) -> TempoMap:
    beats = [first_ms + 500 * i for i in range(n_beats)]
    return TempoMap.from_beats(beats, beats[::4])


def fake_transcription(stem: str, notes: list[tuple[int, int, int, float]], dur_ms: int):
    frames = np.arange(0, dur_ms, 11.6)
    return SimpleNamespace(
        stem=stem,
        notes=[SourceNote(s, e, p, a, stem) for s, e, p, a in notes],
        frame_times_ms=frames,
        rms_db=np.full(len(frames), -20.0),
        active_db=-50.0,
    )


# ---------- ritmo ----------

def test_tempo_map_roundtrip_and_lead_in():
    t = tempo_120()
    assert t.beat_to_ms(0) == 0
    assert t.ms_to_beat(500) == pytest.approx(1.0)  # un pulso de entrada antes del primero
    for ms in (500, 1234, 40000):
        assert t.beat_to_ms(t.ms_to_beat(ms)) == pytest.approx(ms, abs=1)
    assert t.bpm_at(10) == pytest.approx(120)


def test_tempo_map_fills_gaps():
    beats = [500 + 500 * i for i in range(10)] + [500 + 500 * i for i in range(30, 60)]
    t = TempoMap.from_beats(beats, beats[::4])
    assert all(abs(t.bpm_at(b) - 120) < 1 for b in range(1, 50))


def test_two_four_becomes_four_four():
    beats = [500 + 500 * i for i in range(100)]
    assert TempoMap.from_beats(beats, beats[::2]).beats_per_measure == 4


def test_quantize_prefers_sixteenths():
    assert quantize(1.26) == 1.25
    assert quantize(1.33) == pytest.approx(4 / 3)
    assert quantize(1.30) == 1.25


# ---------- mapeo ----------

def test_rank_fret_neighbours_stay_neighbours():
    window = np.array([40, 43, 45, 40, 43, 45])
    assert [_rank_fret(p, window) for p in (40, 43, 45)] == [1, 2, 3]


def test_contour_step_direction():
    assert _contour_step(2, +2, 2) == 3
    assert _contour_step(2, -2, 2) == 1
    assert _contour_step(0, +12, 4) >= 2  # salto grande, paso grande
    assert _contour_step(4, +3, 4) != 4  # en el extremo no repite botón con otra altura


def test_map_expert_contour_chords_hopos_sustains():
    t = tempo_120()
    b = t.beat_to_ms
    notes = [
        (b(4), b(4.4), 40, 0.8),  # escala ascendente en corcheas
        (b(4.5), b(4.9), 42, 0.8),
        (b(5), b(5.4), 44, 0.8),
        (b(5.5), b(5.9), 45, 0.8),
        (b(6), b(6.2), 45, 0.8),  # repetida -> mismo botón
        (b(6.25), b(6.4), 47, 0.8),  # semicorchea fuerte -> HOPO
        (b(8), b(10), 40, 0.8), (b(8), b(10), 47, 0.8),  # acorde largo -> sustain
    ]
    trans = {"guitar": fake_transcription("guitar", notes, b(20))}
    out, sections, _ = map_expert(trans, t, t.ms_to_beat(b(20)), MapParams())
    frets = [n.frets for n in out]
    singles = [f[0] for f in frets[:4]]
    assert singles == sorted(singles) and len(set(singles)) == 4
    assert frets[4] == frets[3]
    assert out[5].hopo and not out[4].hopo
    assert len(out[6].frets) == 2 and out[6].sustain_ms >= 900
    with_notes = [s for s in sections if any(s.start_beat <= n.beat < s.end_beat for n in out)]
    assert with_notes and all(s.stem == "guitar" for s in with_notes)


# ---------- exportación ----------

def test_exports_agree(tmp_path):
    t = tempo_120()
    b = t.beat_to_ms
    notes = [(b(4 + i * 0.5), b(4.4 + i * 0.5), 40 + (i % 5) * 2, 0.8) for i in range(30)]
    trans = {"guitar": fake_transcription("guitar", notes, b(30))}
    out, sections, _ = map_expert(trans, t, t.ms_to_beat(b(30)), MapParams())
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"")
    song = SongInfo("Título", "Artista", "", b(30), "0" * 64, str(audio))

    data = chart_json(song, t, {"expert": out}, sections, "test")
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(data, json.loads((ROOT / "shared" / "chart_schema.json").read_text(encoding="utf-8")))

    folder = write_clonehero(tmp_path / "ch", song, t, {"expert": out}, sections)
    txt = (folder / "notes.chart").read_text(encoding="utf-8-sig")
    ticks = sorted({int(x) for x, f in re.findall(r"^\s*(\d+) = N (\d) \d+", txt, re.M) if int(f) < 5})
    bpm = int(re.search(r"= B (\d+)", txt.split("[SyncTrack]")[1]).group(1)) / 1000
    for tick, n in zip(ticks, data["difficulties"]["expert"]["notes"]):
        assert tick / RESOLUTION * 60000 / bpm == pytest.approx(n["time_ms"], abs=1)
