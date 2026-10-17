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
    # Tramo enérgico: caben semicorcheas.
    out, sections, _ = map_expert(trans, t, t.ms_to_beat(b(20)), MapParams(default_energy=0.9))
    frets = [n.frets for n in out]
    singles = [f[0] for f in frets[:4]]
    assert singles == sorted(singles) and len(set(singles)) == 4
    assert frets[4] == frets[3]
    assert out[5].hopo and not out[4].hopo
    assert len(out[6].frets) == 2 and out[6].sustain_ms >= 900
    with_notes = [s for s in sections if any(s.start_beat <= n.beat < s.end_beat for n in out)]
    assert with_notes and all(s.stem == "guitar" for s in with_notes)


def test_energy_sets_density_and_keeps_strong_beats():
    t = tempo_120()
    b = t.beat_to_ms
    # Corcheas durante 8 compases, con la nota del tiempo fuerte más fuerte.
    notes = [(b(1 + i * 0.5), b(1.4 + i * 0.5), 40 + (i % 3), 0.9 if i % 2 == 0 else 0.5) for i in range(64)]
    trans = {"guitar": fake_transcription("guitar", notes, b(40))}
    end = t.ms_to_beat(b(40))
    calm, _, _ = map_expert(trans, t, end, MapParams(default_energy=0.0))
    loud, _, _ = map_expert(trans, t, end, MapParams(default_energy=1.0))
    assert len(calm) < len(loud) <= 64
    assert len(calm) <= 0.75 * 32 + 4  # ~0,75 notas por pulso
    assert sum(n.beat % 1 == 0 for n in calm) / len(calm) > 0.8  # en lo tranquilo, sobre todo tiempos fuertes


# ---------- ritmo marcado a mano ----------

def test_tap_offset_estimation():
    from generator.taps import estimate_offset

    peaks = np.arange(0, 60000, 500.0)
    taps = [int(x + 70 + (i % 3) * 5) for i, x in enumerate(peaks[10:40])]
    assert estimate_offset(taps, peaks)[0] == pytest.approx(75, abs=5)
    assert estimate_offset(taps[:5], peaks) == (0, 0.0)  # pocos datos: no se corrige
    # Retardo mayor que medio intervalo entre acentos (el ataque más cercano sería el siguiente).
    peaks = np.arange(0, 60000, 400.0)
    off, score = estimate_offset([int(x + 250) for x in peaks[10:40]], peaks)
    assert off == pytest.approx(250, abs=5) and score == 1.0


def test_taps_drive_the_chart(tmp_path):
    from generator.taps import Taps

    t = tempo_120()
    b = t.beat_to_ms
    # Transcripción con corcheas por todas partes...
    notes = [(b(1 + i * 0.5), b(1.4 + i * 0.5), 40 + (i % 4), 0.8) for i in range(70)]
    trans = {"guitar": fake_transcription("guitar", notes, b(40))}
    # ...pero el ritmo marcado entre los pulsos 9 y 17 es "ta ta taaaa" por compás (+60 ms de retardo).
    lag = 60
    taps_list = []
    for m in (9, 13):
        taps_list += [(b(m) + lag, b(m) + 100 + lag), (b(m + 1) + lag, b(m + 1) + 100 + lag),
                      (b(m + 2) + lag, b(m + 3.5) + lag)]
    taps = Taps(tmp_path / "x.json", taps_list, [(b(9) - 100, b(17) - 100)], offset_ms=lag)
    out, _, _ = map_expert(trans, t, t.ms_to_beat(b(40)), MapParams(), taps=taps)
    inside = [n for n in out if b(9) - 100 <= n.time_ms <= b(17) - 100]
    assert [n.beat for n in inside] == [9, 10, 11, 13, 14, 15]
    assert [n.sustain_ms > 0 for n in inside] == [False, False, True] * 2
    assert any(n.beat < 9 for n in out) and any(n.beat > 17 for n in out)  # fuera, el automático


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


# ---------- modelo propio (OnsetNet), sin GPU ----------

def test_fret_labels_and_targets():
    from generator.learn.model import combo, combo_frets
    from generator.learn.train import fret_labels, fret_target

    assert combo([0, 2]) == 5 and combo_frets(5) == [0, 2]
    # tiempo ms, duración, 5 botones: verde suelta, rojo+amarillo, nota al aire (se descarta)
    notes = np.array([[1000, 0, 1, 0, 0, 0, 0], [1100, 0, 0, 1, 1, 0, 0], [2000, 0, 0, 0, 0, 0, 0]], np.float32)
    frames, combos = fret_labels(notes)
    assert list(combos) == [1, 6] and len(frames) == 2
    empty = (np.zeros(0, np.int64), np.zeros(0, np.int64))
    t = fret_target([(frames, combos), empty, empty, empty], a=80, length=40)
    f0, f1 = frames - 80
    assert t[f0, 0] == 1 and t[f1, 0] == 6 and t[f1 + 1, 0] == 6 and t[f0 - 1, 0] == 1
    assert (t[:, 1:] == -100).all() and (t[f1 + 2:, 0] == -100).all()


def test_onsetnet_with_frets_shapes_and_init(tmp_path):
    import torch

    from generator.learn.model import N_COMBOS, OnsetNet
    from generator.learn.train import init_from, loss_fn, predict_song

    old = OnsetNet(hidden=16, layers=1)
    torch.save({"model": old.state_dict()}, tmp_path / "old.pt")
    new = OnsetNet(hidden=16, layers=1, frets=True)
    init_from(new, tmp_path / "old.pt")
    w_old, w_new = old.head[1].weight, new.head[1].weight
    assert w_new.shape[0] == 12 + 4 * N_COMBOS and torch.equal(w_new[:12], w_old)

    x = torch.randn(2, 64, 83)
    logits = new(x)
    z = torch.zeros(2, 64, 4)
    fr = torch.full((2, 64, 4), -100, dtype=torch.long)
    fr[0, 10, 0] = 5
    assert loss_fn(logits, z, z, z, torch.ones(2, 1, 4), fr) > loss_fn(logits, z, z, z, torch.ones(2, 1, 4))

    probs = predict_song(new, np.random.randn(100, 82).astype(np.float32), "cpu", chunk=64, overlap=16)
    combos = probs[:, 12:].reshape(100, 4, N_COMBOS)
    assert np.allclose(combos.sum(-1), 1, atol=1e-4) and combos[..., 0].max() < 1e-6
