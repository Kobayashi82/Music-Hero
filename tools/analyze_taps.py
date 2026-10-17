"""Compara el ritmo marcado a mano (data/taps) con cada fuente posible del audio.

Uso:
    uv run --project generator python tools/analyze_taps.py            # todas las canciones con toques
    uv run --project generator python tools/analyze_taps.py "Give Up"  # filtrar por nombre

Para cada fuente (notas de cada pista, ataques de la batería, acentos del conjunto,
chart automático) busca el mejor desfase global y mide, dentro de los tramos marcados:
    recall     % de toques con un evento de la fuente a menos de 80 ms
    precision  % de eventos de la fuente que caen sobre un toque
    F1         media armónica de las dos
Necesita los stems ya separados (out/charts/<canción>/stems): ejecutar antes `generate`.
"""

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TOL = 80


def match(taps: np.ndarray, events: np.ndarray, offset: float) -> tuple[float, float]:
    if len(taps) == 0 or len(events) == 0:
        return 0.0, 0.0
    ev = np.sort(events + offset)
    i = np.clip(np.searchsorted(ev, taps), 1, len(ev) - 1)
    d_t = np.minimum(abs(taps - ev[i - 1]), abs(taps - ev[i]))
    recall = float((d_t <= TOL).mean())
    j = np.clip(np.searchsorted(taps, ev), 1, len(taps) - 1)
    d_e = np.minimum(abs(ev - taps[j - 1]), abs(ev - taps[j]))
    precision = float((d_e <= TOL).mean())
    return recall, precision


def best(taps: np.ndarray, events: np.ndarray) -> tuple[float, float, float, int]:
    out = (0.0, 0.0, 0.0, 0)
    for off in range(-150, 151, 5):
        r, p = match(taps, events, off)
        f = 2 * r * p / (r + p) if r + p else 0.0
        if f > out[0]:
            out = (f, r, p, off)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from generator.audio import song_info
    from generator.feel import analyze
    from generator.mapping import MapParams, map_expert
    from generator.model import MELODIC_STEMS
    from generator.rhythm import TempoMap, detect_beats
    from generator.taps import accent_peaks
    from generator.transcribe import AUDIO_SAMPLE_RATE, detect_onsets, transcribe
    from generator.audio import load_mono
    import librosa

    filt = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    for tf in sorted((ROOT / "data" / "taps").glob("*.json")):
        data = json.loads(tf.read_text(encoding="utf-8"))
        if not data["taps"] or filt not in tf.stem.lower():
            continue
        audio = Path(data["audio_file"])
        stems = ROOT / "out" / "charts" / audio.stem / "stems"
        covered = data["covered"]

        def inside(arr):
            arr = np.asarray(arr, dtype=float)
            m = np.zeros(len(arr), bool)
            for a, b in covered:
                m |= (arr >= a) & (arr <= b)
            return arr[m]

        taps = np.array(sorted(a for a, _ in data["taps"]), dtype=float)
        beats, downbeats = detect_beats(audio)
        tempo = TempoMap.from_beats(beats, downbeats)
        trans = {s: transcribe(stems / f"{s}.flac", s) for s in MELODIC_STEMS}
        feel = analyze(audio, stems / "drums.flac")
        sources = {}
        for s, t in trans.items():
            sources[f"notas {s}"] = [n.start_ms for n in t.notes if n.origin == "bp" and n.amp >= 0.3]
        drums = load_mono(stems / "drums.flac", AUDIO_SAMPLE_RATE)
        sources["ataques batería"] = detect_onsets(drums, 0.25, librosa)
        for th in (0.4, 0.6, 0.8):
            sources[f"acentos conjunto ≥{th}"] = accent_peaks(feel, th)
        sources["pulsos"] = beats
        sources["pulsos + corcheas"] = [tempo.beat_to_ms(b / 2) for b in range(int(tempo.ms_to_beat(beats[-1]) * 2))]
        song = song_info(audio)
        auto, _, _ = map_expert(trans, tempo, tempo.ms_to_beat(song.duration_ms), MapParams(), feel=feel)
        sources["chart automático v0.2"] = [n.time_ms for n in auto]

        tap_beats = np.array([tempo.ms_to_beat(t) for t in taps])
        ioi = np.diff(tap_beats)
        print(f"\n=== {data['artist']} - {data['title']}: {len(taps)} toques, ~{tempo.bpm_at(20):.0f} BPM, "
              f"{len(taps) / sum(b - a for a, b in covered) * 1000:.2f} toques/s")
        print(f"    separación entre toques (pulsos): mediana {np.median(ioi):.2f}, "
              f"p25 {np.percentile(ioi, 25):.2f}, p75 {np.percentile(ioi, 75):.2f}")
        frac = tap_beats % 1
        print(f"    toques en el pulso {np.mean((frac < 0.12) | (frac > 0.88)):.0%}, "
              f"en la corchea {np.mean(abs(frac - 0.5) < 0.12):.0%}")
        rows = []
        for name, ev in sources.items():
            ev = inside(ev)
            f, r, p, off = best(taps, ev)
            rows.append((f, name, r, p, off, len(ev)))
        print(f"    {'fuente':<24} {'F1':>5} {'recall':>7} {'precis.':>8} {'desfase':>8} {'eventos':>8}")
        for f, name, r, p, off, n in sorted(rows, reverse=True):
            print(f"    {name:<24} {f:5.2f} {r:7.0%} {p:8.0%} {off:6d} ms {n:8d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
