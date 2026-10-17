"""Preparación de datos: paquete .sng (audio + chart humana) -> características y etiquetas por fotograma.

Por canción se guardan <md5>.feats.npy (se lee a trozos con mmap) y <md5>.npz:
    feats   (T, 82) float16: log-mel de la mezcla (80) + activaciones de pulso y compás de Beat This (2)
    onset   (4, T)  uint8:   1 en el fotograma donde empieza una nota (Experto, Difícil, Medio, Fácil)
    sustain (4, T)  uint8:   1 mientras dura una nota sostenida
    chord   (4, T)  uint8:   1 en el inicio de un acorde
    notes_<dif>     (N, 7) float32: tiempo ms, duración ms, 5 botones (0/1), para etapas posteriores

Uso:
    uv run --project generator python -m generator.learn.data out/dataset/sng out/dataset/feat
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

SR = 22050
HOP = 256
FPS = SR / HOP  # ~86,13 fotogramas por segundo
N_MELS = 80
DIFFS = ("expert", "hard", "medium", "easy")
SKIP_AUDIO = ("crowd", "preview")


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


def mix_package_audio(files: dict[str, bytes]) -> np.ndarray | None:
    audio = [(n, d) for n, d in files.items()
             if Path(n).suffix.lower() in (".opus", ".ogg", ".mp3", ".wav", ".flac")
             and not any(s in Path(n).stem.lower() for s in SKIP_AUDIO)]
    mix = None
    for name, data in audio:
        y = decode_audio(name, data)
        if mix is None:
            mix = y
        else:
            n = max(len(mix), len(y))
            mix = np.pad(mix, (0, n - len(mix))) + np.pad(y, (0, n - len(y)))
    if mix is None:
        return None
    peak = np.abs(mix).max()
    return mix / peak if peak > 0 else mix


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


def features(y: np.ndarray, device: str = "cuda") -> np.ndarray:
    mel = log_mel(y)
    mel = (mel - mel.mean()) / (mel.std() + 1e-6)
    beats = beat_activations(y, len(mel), device)
    return np.concatenate([mel, beats], axis=1)


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


def prepare(sng: Path, out_dir: Path, device: str = "cuda") -> Path | None:
    from ..human import read_chart, read_mid
    from ..sng import read_sng

    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{sng.stem}.npz"
    if dest.exists():
        return dest
    meta, files = read_sng(sng)
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
    y = mix_package_audio(files)
    if y is None or len(y) < SR * 30:
        return None
    feats = features(y, device)
    lab = labels(diffs, len(feats))
    np.save(out_dir / f"{sng.stem}.feats.npy", feats.astype(np.float16))
    np.savez_compressed(dest, **lab, meta=json.dumps({k: meta.get(k) for k in ("artist", "name", "charter", "genre")}))
    return dest


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    follow = "--follow" in sys.argv  # seguir procesando lo que vaya llegando de la descarga
    failed: set[str] = set()
    t0, done = time.time(), 0
    while True:
        pending = [p for p in sorted(src.glob("*.sng"))
                   if not (out / f"{p.stem}.npz").exists() and p.stem not in failed]
        if not pending:
            if not follow:
                break
            time.sleep(30)
            if (src / "DONE").exists() and not [p for p in src.glob("*.sng") if not (out / f"{p.stem}.npz").exists()
                                                 and p.stem not in failed]:
                break
            continue
        for p in pending:
            try:
                r = prepare(p, out)
                if r is None:
                    failed.add(p.stem)
                done += 1
            except Exception as e:  # noqa: BLE001 - un paquete raro no para el resto
                failed.add(p.stem)
                print(f"   fallo {p.name}: {e}")
            if done % 50 == 0 and done:
                print(f"{done} preparadas ({len(failed)} descartadas), {(time.time() - t0) / max(1, done):.1f} s/canción")
    print(f"Fin: {done} procesadas, {len(failed)} descartadas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
