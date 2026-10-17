"""generate canción.mp3 -> chart.json + vista previa HTML (+ carpeta para YARG/Clone Hero).

Uso:
    uv run --project generator generate "D:/Musica/Artista - Canción.mp3"
    uv run --project generator generate canción.mp3 --clonehero      # también notes.chart + song.ini
"""

import argparse
import sys
import time
from pathlib import Path

from . import __version__

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = ROOT / "out" / "charts"


def generate(audio: Path, out_root: Path, clonehero: bool = False, device: str = "cuda") -> Path:
    from .audio import song_info
    from .export_chart import chart_json, write_clonehero, write_json
    from .mapping import map_expert
    from .model import MELODIC_STEMS
    from .preview import write_preview
    from .rhythm import TempoMap, detect_beats
    from .separate import separate
    from .transcribe import transcribe

    t0 = time.perf_counter()
    out = out_root / audio.stem
    out.mkdir(parents=True, exist_ok=True)

    def step(msg: str) -> None:
        print(f"  [{time.perf_counter() - t0:5.1f} s] {msg}", flush=True)

    song = song_info(audio)
    print(f"{song.artist} - {song.title}  ({song.duration_ms / 1000:.0f} s)")

    stems = separate(audio, out / "stems", device)
    step("pistas separadas (Demucs htdemucs_6s)")

    beats, downbeats = detect_beats(audio, device)
    tempo = TempoMap.from_beats(beats, downbeats)
    step(f"{len(beats)} pulsos, {len(downbeats)} compases, ~{tempo.bpm_at(len(beats) / 2):.0f} BPM, "
         f"{tempo.beats_per_measure}/4")

    trans = {s: transcribe(stems[s], s) for s in MELODIC_STEMS}
    step("notas: " + ", ".join(f"{s} {len(t.notes)}" for s, t in trans.items()))

    end_beat = tempo.ms_to_beat(song.duration_ms)
    notes, sections, source = map_expert(trans, tempo, end_beat)
    step(f"chart Experto: {len(notes)} notas")

    data = chart_json(song, tempo, {"expert": notes}, sections, __version__)
    write_json(out / "chart.json", data)
    write_preview(out / "preview.html", song, tempo, notes, sections, source, __version__)
    if clonehero:
        write_clonehero(out / "clonehero", song, tempo, {"expert": notes}, sections)
    step(f"listo: {out}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", type=Path, nargs="+")
    parser.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT, help=f"carpeta de salida (por defecto {DEFAULT_OUT})")
    parser.add_argument("--clonehero", action="store_true", help="exporta también notes.chart + song.ini + audio")
    parser.add_argument("--cpu", action="store_true", help="sin GPU")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    for audio in args.audio:
        generate(audio, args.out, args.clonehero, "cpu" if args.cpu else "cuda")
    return 0


if __name__ == "__main__":
    sys.exit(main())
