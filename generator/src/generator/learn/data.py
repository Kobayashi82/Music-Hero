"""Preparación de datos: paquete .sng (audio + chart humana) -> características y etiquetas por fotograma.

Por canción se guardan <md5>.feats.npy (se lee a trozos con mmap) y <md5>.npz:
    feats   (T, 82) float16: log-mel de la mezcla (80) + activaciones de pulso y compás de Beat This (2)
            con --guitar (modelos v5+), (T, 234): log-mel de la mezcla (80), log-mel de la pista de guitarra (80),
            CQT de la guitarra (72, un semitono por banda desde Mi1: la altura, para los botones) y pulso/compás (2)
    onset   (4, T)  uint8:   1 en el fotograma donde empieza una nota (Experto, Difícil, Medio, Fácil)
    sustain (4, T)  uint8:   1 mientras dura una nota sostenida
    chord   (4, T)  uint8:   1 en el inicio de un acorde
    notes_<dif>     (N, 7) float32: tiempo ms, duración ms, 5 botones (0/1), para etapas posteriores

Uso:
    uv run --project generator python -m generator.learn.data out/dataset/sng out/dataset/feat [--follow] [--shard 0/4]
    uv run --project generator python -m generator.learn.data out/dataset/sng out/dataset/feat5 --guitar [--shard 0/4]

--guitar usa la pista de guitarra del paquete (guitar*.ogg...); los que no la traen se saltan, salvo con
--demucs, que la separa con Demucs (htdemucs_6s, como al generar).

--shard k/n reparte el trabajo entre n procesos (cada uno hace los paquetes con md5 % n == k).
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from ..i18n import t

SR = 22050
HOP = 256
FPS = SR / HOP  # ~86,13 fotogramas por segundo
N_MELS = 80
DIFFS = ("expert", "hard", "medium", "easy")
SKIP_AUDIO = ("crowd", "preview")
N_CQT = 72
CQT_FMIN = 41.2  # Mi1: una octava por debajo de la guitarra (Mi2), por el bajo de los acordes
N_FEATS_GUITAR = 2 * N_MELS + N_CQT + 2


def ms_to_frame(ms: float) -> int:
    return int(round(ms / 1000 * FPS))


def decode_audio(name: str, data: bytes) -> np.ndarray:
    """Audio del paquete en mono a SR. libsndfile lee de memoria; si no puede, ffmpeg con un temporal."""
    import soundfile as sf
    import soxr

    try:
        y, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        y = y.mean(axis=1)
        return soxr.resample(y, sr, SR) if sr != SR else y
    except Exception:  # noqa: BLE001
        from ..audio import _ffmpeg_mono

        with tempfile.NamedTemporaryFile(suffix=Path(name).suffix, delete=False) as f:
            f.write(data)
            tmp = Path(f.name)
        try:
            return _ffmpeg_mono(tmp, SR)
        finally:
            tmp.unlink(missing_ok=True)


def _sum(tracks: list[np.ndarray]) -> np.ndarray | None:
    if not tracks:
        return None
    n = max(len(t) for t in tracks)
    return sum(np.pad(t, (0, n - len(t))) for t in tracks)


def package_tracks(files: dict[str, bytes]) -> tuple[np.ndarray | None, np.ndarray | None]:
    """(mezcla normalizada a pico 1, pista de guitarra con la misma escala o None si el paquete no la trae)."""
    audio = [(n, d) for n, d in files.items()
             if Path(n).suffix.lower() in (".opus", ".ogg", ".mp3", ".wav", ".flac")
             and not any(s in Path(n).stem.lower() for s in SKIP_AUDIO)]
    decoded = [(Path(n).stem.lower(), decode_audio(n, d)) for n, d in audio]
    mix = _sum([y for _, y in decoded])
    if mix is None:
        return None, None
    guitar = _sum([y for name, y in decoded if name.startswith("guitar")])
    if all(name.startswith("guitar") for name, _ in decoded):  # una sola pista "guitar" con todo: no es la guitarra
        guitar = None
    peak = np.abs(mix).max()
    if peak > 0:
        mix = mix / peak
        guitar = guitar / peak if guitar is not None else None
    return mix, guitar


def mix_package_audio(files: dict[str, bytes]) -> np.ndarray | None:
    return package_tracks(files)[0]


def log_mel(y: np.ndarray) -> np.ndarray:
    import librosa

    m = librosa.feature.melspectrogram(y=y, sr=SR, n_fft=2048, hop_length=HOP, n_mels=N_MELS, fmin=30, fmax=11000)
    return np.log(m + 1e-6).T.astype(np.float32)  # (T, 80)


_beat_model = None


def beat_activations(y: np.ndarray, n_frames: int, device: str = "cuda") -> np.ndarray:
    """Logits de pulso y compás de Beat This (50 fps) llevados a FPS. (T, 2)"""
    global _beat_model
    import torch
    from beat_this.inference import Audio2Frames

    if _beat_model is None:
        _beat_model = Audio2Frames(checkpoint_path="final0", device=device)
    with torch.no_grad():
        beat, down = _beat_model(y, SR)
    src = np.arange(len(beat)) / 50.0
    dst = np.arange(n_frames) / FPS
    b = np.interp(dst, src, beat.cpu().numpy())
    d = np.interp(dst, src, down.cpu().numpy())
    return np.stack([b, d], axis=1).astype(np.float32) / 10.0


def features(y: np.ndarray, device: str = "cuda", guitar: np.ndarray | None = None) -> np.ndarray:
    """y: mezcla a pico 1. Con guitar (misma escala que y), las características de los modelos v5+."""
    mel = log_mel(y)
    mean, std = mel.mean(), mel.std() + 1e-6
    mel = (mel - mean) / std
    beats = beat_activations(y, len(mel), device)
    if guitar is None:
        return np.concatenate([mel, beats], axis=1)
    g = np.pad(guitar, (0, max(0, len(y) - len(guitar))))[:len(y)]
    g_mel = (log_mel(g) - mean) / std  # con la escala de la mezcla: una guitarra callada se ve callada
    return np.concatenate([mel, g_mel, guitar_cqt(g), beats], axis=1)


def guitar_cqt(g: np.ndarray) -> np.ndarray:
    """(T, 72) log-CQT, un semitono por banda; escala fija (no por canción) para que el silencio siga siéndolo."""
    import librosa

    c = np.abs(librosa.cqt(g, sr=SR, hop_length=HOP, fmin=CQT_FMIN, n_bins=N_CQT, bins_per_octave=12))
    return ((np.log(c + 1e-4) + CQT_SHIFT) / CQT_SCALE).T.astype(np.float32)


CQT_SHIFT, CQT_SCALE = 5.0, 3.0  # log(c + 1e-4) va de -9,2 (silencio) a ~+2: queda en ~-1,4..2,3


def demucs_guitar(mix: np.ndarray, device: str = "cuda") -> np.ndarray:
    """Pista de guitarra de Demucs (htdemucs_6s, la misma separación que al generar), en mono y a SR."""
    global _separator
    import soxr
    import torch
    from demucs.api import Separator

    if _separator is None:
        _separator = Separator(model="htdemucs_6s", device=device)
    sr = _separator.samplerate
    x = soxr.resample(mix, SR, sr).astype(np.float32)
    with torch.no_grad():
        _, stems = _separator.separate_tensor(torch.from_numpy(np.stack([x, x])), sr)
    g = stems["guitar"].mean(dim=0).cpu().numpy()
    return soxr.resample(g, sr, SR).astype(np.float32)


_separator = None


def labels(diffs: dict, n_frames: int) -> dict[str, np.ndarray]:
    onset = np.zeros((4, n_frames), np.uint8)
    sustain = np.zeros((4, n_frames), np.uint8)
    chord = np.zeros((4, n_frames), np.uint8)
    out = {}
    for k, d in enumerate(DIFFS):
        rows = []
        for n in diffs.get(d, []):
            f = ms_to_frame(n.time_ms)
            if not 0 <= f < n_frames:
                continue
            onset[k, f] = 1
            if len(n.frets) > 1:
                chord[k, f] = 1
            if n.sustain_ms:
                sustain[k, f:min(n_frames, ms_to_frame(n.time_ms + n.sustain_ms))] = 1
            row = [n.time_ms, n.sustain_ms] + [1.0 if i in n.frets else 0.0 for i in range(5)]
            rows.append(row)
        out[f"notes_{d}"] = np.array(rows, np.float32).reshape(-1, 7)
    return {"onset": onset, "sustain": sustain, "chord": chord, **out}


def prepare(sng: Path, out_dir: Path, device: str = "cuda", guitar: bool = False, demucs: bool = False) -> Path | None:
    """None si el paquete no vale (sin chart de guitarra, muy corto o, con guitar y sin demucs, sin su pista)."""
    from ..human import read_chart, read_mid
    from ..sng import read_sng

    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{sng.stem}.npz"
    if dest.exists():
        return dest
    meta, files = read_sng(sng)
    if guitar and not demucs and not any(Path(n).stem.lower().startswith("guitar") for n in files):
        return None  # sin pista de guitarra: ni se descodifica
    if "notes.chart" in files:
        diffs = read_chart(files["notes.chart"].decode("utf-8-sig", errors="replace"))
    elif "notes.mid" in files:
        diffs = read_mid(files["notes.mid"])
    else:
        return None
    if not diffs.get("expert"):
        return None
    delay = int(float(meta.get("delay", 0) or 0))
    if delay:
        for notes in diffs.values():
            for n in notes:
                n.time_ms += delay
    y, g = package_tracks(files)
    if y is None or len(y) < SR * 30:
        return None
    if guitar and g is None:
        if not demucs:
            return None
        g = demucs_guitar(y, device)
    feats = features(y, device, g if guitar else None)
    lab = labels(diffs, len(feats))
    np.save(out_dir / f"{sng.stem}.feats.npy", feats.astype(np.float16))
    np.savez_compressed(dest, **lab, meta=json.dumps({k: meta.get(k) for k in ("artist", "name", "charter", "genre")}))
    return dest


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    follow = "--follow" in sys.argv  # seguir procesando lo que vaya llegando de la descarga
    guitar, demucs = "--guitar" in sys.argv, "--demucs" in sys.argv
    k, n = 0, 1
    if "--shard" in sys.argv:
        k, n = map(int, sys.argv[sys.argv.index("--shard") + 1].split("/"))
    mine = lambda p: int(p.stem, 16) % n == k if len(p.stem) == 32 else k == 0  # noqa: E731
    failed: set[str] = set()
    t0, done = time.time(), 0
    while True:
        pending = [p for p in sorted(src.glob("*.sng"))
                   if mine(p) and not (out / f"{p.stem}.npz").exists() and p.stem not in failed]
        if not pending:
            if not follow:
                break
            time.sleep(30)
            if (src / "DONE").exists() and not [p for p in src.glob("*.sng") if mine(p) and not (out / f"{p.stem}.npz").exists()
                                                 and p.stem not in failed]:
                break
            continue
        for p in pending:
            try:
                r = prepare(p, out, guitar=guitar, demucs=demucs)
                if r is None:
                    failed.add(p.stem)
                done += 1
            except Exception as e:  # noqa: BLE001 - un paquete raro no para el resto
                failed.add(p.stem)
                print("   " + t("fallo {name}: {err}", name=p.name, err=e))
            if done % 50 == 0 and done:
                print(t("{done} preparadas ({failed} descartadas), {secs:.1f} s/canción", done=done, failed=len(failed),
                        secs=(time.time() - t0) / max(1, done)))
    print(t("Fin: {done} procesadas, {failed} descartadas", done=done, failed=len(failed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
