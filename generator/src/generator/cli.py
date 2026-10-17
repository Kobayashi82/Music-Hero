"""generate canción.mp3 | carpeta/ -> chart.json + vista previa HTML (+ carpeta para YARG/Clone Hero).

Uso:
    uv run --project generator generate "D:/Musica/Artista - Canción.mp3"
    uv run --project generator generate "D:/Musica/Artista"            # toda la carpeta (y subcarpetas)
    uv run --project generator generate carpeta/ --jobs 2              # dos canciones a la vez
    uv run --project generator generate canción.mp3 --clonehero      # también notes.chart + song.ini
    uv run --project generator generate canción.mp3 --human chart.sng # chart hecha por personas, sincronizada

Por defecto usa el modelo models/best.pt (las 4 dificultades); --no-model, las reglas (solo Experto).
Caché: si out/<canción>/chart.json ya es de ese mismo audio (hash) y de esta versión del generador
y del modelo, la canción se salta; --force la rehace. Los stems de Demucs se guardan para no repetirlo
(~50 MB por canción); --drop-stems los borra al terminar.
"""

import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from . import __version__

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = ROOT / "out" / "charts"
DEFAULT_MODEL = ROOT / "models" / "best.pt"
AUDIO_EXT = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".wma"}


def find_audio(paths: list[str]) -> list[Path]:
    """Archivos de audio de la lista; las carpetas se recorren enteras. Una ruta vacía, que no existe
    o que no es audio es un error (una vacía sería la carpeta actual: recorrería todo el proyecto)."""
    out = []
    for raw in paths:
        if not str(raw).strip():
            raise ValueError("ruta vacía")
        p = Path(raw)
        if not p.exists():
            raise ValueError(f"no existe: {p}")
        if p.is_file() and p.suffix.lower() not in AUDIO_EXT:
            raise ValueError(f"no es un archivo de audio: {p}")
        if p.is_dir():
            out += sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in AUDIO_EXT)
        else:
            out.append(p)
    return out


def generator_version(model_path: Path | None, human_chart: Path | None, max_nps: dict[str, float] | None = None) -> str:
    """Versión que se guarda en chart.json: cambia si cambia el algoritmo, el modelo, la chart humana
    o los límites de densidad."""
    from .audio import sha256_file

    v = __version__
    if human_chart is not None:
        v += f"+humana-{sha256_file(human_chart)[:8]}" if human_chart.is_file() else f"+humana-{human_chart.name}"
    elif model_path is not None:
        v += f"+{model_path.stem}-{sha256_file(model_path)[:8]}"
        if max_nps:
            v += "+nps-" + "-".join(f"{k}{n:g}" for k, n in sorted(max_nps.items()))
    return v


def _chart_of(out: Path) -> dict | None:
    try:
        return json.loads((out / "chart.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def out_dir_for(audio: Path, sha: str, out_root: Path) -> Path:
    """out/<nombre>; si ahí ya hay la chart de otro audio con el mismo nombre, out/<nombre> (<hash>)."""
    out = out_root / audio.stem
    old = _chart_of(out)
    if old is not None and old.get("song", {}).get("audio_sha256") not in (None, sha):
        out = out_root / f"{audio.stem} ({sha[:8]})"
    return out


def up_to_date(out: Path, sha: str, version: str, clonehero: bool = False) -> bool:
    c = _chart_of(out)
    return (c is not None and c.get("song", {}).get("audio_sha256") == sha
            and c.get("generator", {}).get("version") == version
            and (out / "preview.html").exists() and (not clonehero or (out / "clonehero").exists()))


def generate(audio: Path, out_root: Path, clonehero: bool = False, device: str = "cuda",
             human_chart: Path | None = None, model_path: Path | None = None, force: bool = False,
             max_nps: dict[str, float] | None = None, drop_stems: bool = False, tag: str = "") -> Path | None:
    """Genera la chart de una canción. Devuelve su carpeta, o None si ya estaba hecha (caché)."""
    from .audio import song_info

    t0 = time.perf_counter()

    def step(msg: str) -> None:
        print(f"{tag}  [{time.perf_counter() - t0:5.1f} s] {msg}", flush=True)

    song = song_info(audio)
    version = generator_version(model_path, human_chart, max_nps)
    out = out_dir_for(audio, song.audio_sha256, out_root)
    if not force and up_to_date(out, song.audio_sha256, version, clonehero):
        print(f"{tag}{audio.name}: ya hecha ({out.name})", flush=True)
        return None
    print(f"{tag}{song.artist} - {song.title}  ({song.duration_ms / 1000:.0f} s)", flush=True)

    from .export_chart import chart_json, write_clonehero, write_json
    from .feel import analyze
    from .mapping import MapParams, map_expert
    from .model import MELODIC_STEMS
    from .preview import write_preview
    from .rhythm import TempoMap, detect_beats
    from .separate import separate
    from .transcribe import transcribe

    out.mkdir(parents=True, exist_ok=True)
    stems = separate(audio, out / "stems", device)
    step("pistas separadas (Demucs htdemucs_6s)")

    beats, downbeats = detect_beats(audio, device)
    tempo = TempoMap.from_beats(beats, downbeats)
    step(f"{len(beats)} pulsos, {len(downbeats)} compases, ~{tempo.bpm_at(len(beats) / 2):.0f} BPM, "
         f"{tempo.beats_per_measure}/4")

    trans = {s: transcribe(stems[s], s) for s in MELODIC_STEMS}
    step("notas: " + ", ".join(f"{s} {len(t.notes)}" for s, t in trans.items()))

    feel = analyze(audio, stems["drums"])
    end_beat = tempo.ms_to_beat(song.duration_ms)
    params = MapParams()
    if max_nps:
        params.max_nps.update(max_nps)
    notes, sections, source = map_expert(trans, tempo, end_beat, params, feel=feel)
    energy = sum(s.energy for s in sections) / max(1, len(sections))
    step(f"chart Experto: {len(notes)} notas, energía media {energy:.2f}")
    difficulties = {"expert": notes}

    if model_path is not None and human_chart is None:
        from .learn.infer import predict
        from .mapping import map_from_model

        difficulties = map_from_model(trans, tempo, sections, predict(audio, model_path, device), params)
        notes = difficulties["expert"]
        step(f"modelo {model_path.name}: " + ", ".join(f"{d} {len(n)}" for d, n in difficulties.items()))

    if human_chart is not None:
        from . import human

        hc = human.load(human_chart)
        alignment = human.align(hc.audio_files, audio)
        difficulties = human.shift(hc.difficulties, alignment, tempo)
        offs = alignment.offsets()
        step(f"chart humana: {hc.name} ({hc.charter}), sincronizada (anclas afinadas {alignment.confidence:.0%}, "
             f"desfase {offs.min() / 1000:+.2f}..{offs.max() / 1000:+.2f} s): "
             + ", ".join(f"{d} {len(n)}" for d, n in difficulties.items()))
        notes = difficulties.get("expert", notes)

    data = chart_json(song, tempo, difficulties, sections, version)
    write_json(out / "chart.json", data)
    write_preview(out / "preview.html", song, tempo, notes, sections, source, version, difficulties)
    if clonehero:
        write_clonehero(out / "clonehero", song, tempo, difficulties, sections)
    if drop_stems:
        shutil.rmtree(out / "stems", ignore_errors=True)
    step(f"listo: {out}")
    return out


def _worker(kw: dict) -> tuple[str, str, float]:
    """Una canción en un proceso aparte: (archivo, 'hecha' | 'saltada' | 'error: ...', segundos)."""
    sys.stdout.reconfigure(line_buffering=True)
    t0 = time.perf_counter()
    try:
        r = generate(**kw)
        status = "saltada" if r is None else "hecha"
    except Exception as e:  # noqa: BLE001 - una canción rara no para el lote
        status = f"error: {type(e).__name__}: {e}"
    return str(kw["audio"]), status, time.perf_counter() - t0


def parse_max_nps(text: str) -> dict[str, float]:
    """'expert=14,easy=3' -> {'expert': 14.0, 'easy': 3.0}"""
    out = {}
    for part in filter(None, (p.strip() for p in text.split(","))):
        k, v = part.split("=")
        if k not in ("expert", "hard", "medium", "easy"):
            raise ValueError(f"dificultad desconocida: {k}")
        out[k] = float(v)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", nargs="+", help="canciones o carpetas")
    parser.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT, help=f"carpeta de salida (por defecto {DEFAULT_OUT})")
    parser.add_argument("--clonehero", action="store_true", help="exporta también notes.chart + song.ini + audio")
    parser.add_argument("--cpu", action="store_true", help="sin GPU")
    parser.add_argument("--human", type=Path, help="chart hecha por personas (.sng o carpeta) para sincronizar y usar")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL,
                        help=f"modelo entrenado para las 4 dificultades (por defecto {DEFAULT_MODEL.name})")
    parser.add_argument("--no-model", action="store_true", help="sin modelo: reglas, solo Experto")
    parser.add_argument("--force", action="store_true", help="rehacer aunque ya esté hecha")
    parser.add_argument("--jobs", type=int, default=1, help="canciones a la vez (cada una en un proceso; 2 va bien en 12 GB)")
    parser.add_argument("--max-nps", type=parse_max_nps, default={},
                        help="notas/s como mucho en 2 s, p. ej. 'expert=14,hard=8,medium=5,easy=3.5'")
    parser.add_argument("--drop-stems", action="store_true", help="borrar los stems al terminar cada canción")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    model = None if args.no_model else args.model
    if model is not None and not model.exists():
        if args.model != DEFAULT_MODEL:
            parser.error(f"no existe el modelo {model}")
        print(f"aviso: no hay {DEFAULT_MODEL}; se usan las reglas (solo Experto)")
        model = None
    try:
        files = find_audio(args.audio)
    except ValueError as e:
        parser.error(str(e))
    if not files:
        parser.error("no hay archivos de audio")
    common = dict(out_root=args.out, clonehero=args.clonehero, device="cpu" if args.cpu else "cuda",
                  human_chart=args.human, model_path=model, force=args.force, max_nps=args.max_nps,
                  drop_stems=args.drop_stems)
    if len(files) == 1:
        generate(files[0], **common)
        return 0

    print(f"{len(files)} canciones, {args.jobs} a la vez, modelo: {model.name if model else 'ninguno (reglas)'}")
    t0, results = time.perf_counter(), []
    jobs = [dict(common, audio=f, tag=f"[{i + 1}/{len(files)}] ") for i, f in enumerate(files)]
    if args.jobs <= 1:
        results = [_worker(kw) for kw in jobs]
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for fut in as_completed([pool.submit(_worker, kw) for kw in jobs]):
                results.append(fut.result())
    done = sum(s == "hecha" for _, s, _ in results)
    skipped = sum(s == "saltada" for _, s, _ in results)
    errors = [(f, s) for f, s, _ in results if s.startswith("error")]
    print(f"\nFin en {(time.perf_counter() - t0) / 60:.1f} min: {done} hechas, {skipped} ya estaban, {len(errors)} con error")
    for f, s in errors:
        print(f"  {Path(f).name}: {s}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
