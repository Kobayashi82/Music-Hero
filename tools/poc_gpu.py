"""Fase 0 - GPU: Demucs (htdemucs_6s) y Basic Pitch funcionando con CUDA en una canción.

Uso:
    uv run --project generator python tools/poc_gpu.py "C:/ruta/cancion.mp3"
    uv run --project generator python tools/poc_gpu.py            # sin archivo: genera un audio sintético

Salida (en out/poc_gpu/<canción>/):
    guitar.wav, bass.wav, ... los 6 stems de Demucs
    guitar.mid                notas de la pista de guitarra según Basic Pitch

La primera vez descarga el modelo htdemucs_6s (~50 MB).
"""

import argparse
import logging
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

# onnxruntime-gpu usa las DLL de CUDA/cuDNN que trae torch; hay que cargarlas antes.
import onnxruntime as ort  # noqa: E402

if hasattr(ort, "preload_dlls"):
    ort.preload_dlls()

logging.getLogger().setLevel(logging.ERROR)  # Basic Pitch avisa de cada backend que no está instalado
warnings.filterwarnings("ignore")

from basic_pitch import ICASSP_2022_MODEL_PATH  # noqa: E402
from basic_pitch.inference import Model, predict  # noqa: E402
from demucs.api import Separator  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def synth_test_song(path: Path, seconds: float = 20.0, sr: int = 44100) -> None:
    """Audio de prueba: guitarra (Karplus-Strong), bajo y bombo a 120 BPM."""
    rng = np.random.default_rng(0)
    out = np.zeros(int(seconds * sr), dtype=np.float32)
    beat = 0.5

    def pluck(freq: float, dur: float) -> np.ndarray:
        n = int(dur * sr)
        period = int(sr / freq)
        buf = rng.uniform(-1, 1, period).astype(np.float32)
        y = np.empty(n, dtype=np.float32)
        for i in range(n):
            y[i] = buf[i % period]
            buf[i % period] = 0.996 * 0.5 * (buf[i % period] + buf[(i + 1) % period])
        return y

    riff = [82.4, 110.0, 123.5, 146.8, 164.8, 146.8, 123.5, 110.0]  # Mi2 La2 Si2 Re3 Mi3 ...
    t = 0.0
    k = 0
    while t + beat < seconds:
        i = int(t * sr)
        note = pluck(riff[k % len(riff)] * 2, beat)
        out[i:i + len(note)] += 0.5 * note
        if k % 2 == 0:
            n = int(beat * 2 * sr)
            bass = np.sin(2 * np.pi * riff[k % len(riff)] / 2 * np.arange(n) / sr) * np.exp(-np.arange(n) / sr * 2)
            out[i:i + n] += 0.4 * bass[: len(out) - i]
        n = int(0.15 * sr)
        kick = np.sin(2 * np.pi * 60 * np.arange(n) / sr) * np.exp(-np.arange(n) / sr * 30)
        out[i:i + n] += 0.6 * kick[: len(out) - i]
        t += beat
        k += 1
    out /= np.abs(out).max() * 1.1
    sf.write(path, np.stack([out, out], axis=1), sr)


def cuda_basic_pitch_model() -> Model:
    """Basic Pitch carga el ONNX solo en CPU; cambiamos la sesión por una con CUDA."""
    model = Model(ICASSP_2022_MODEL_PATH)
    if not str(ICASSP_2022_MODEL_PATH).endswith(".onnx"):
        print(f"  aviso: Basic Pitch está usando {ICASSP_2022_MODEL_PATH}, no ONNX")
        return model
    model.model = ort.InferenceSession(
        str(ICASSP_2022_MODEL_PATH), providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
    )
    return model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", nargs="?", type=Path, help="mp3/wav/flac; si se omite, se genera uno")
    parser.add_argument("--out", type=Path, default=ROOT / "out" / "poc_gpu")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    print(f"torch {torch.__version__}  CUDA disponible: {torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        print("ERROR: torch no ve la GPU. ¿Driver NVIDIA instalado? ¿torch con +cu en la versión?")
        return 1
    print(f"GPU: {torch.cuda.get_device_name(0)}  "
          f"({torch.cuda.get_device_properties(0).total_memory / 2**30:.1f} GB)")
    print(f"onnxruntime {ort.__version__}  proveedores: {ort.get_available_providers()}")

    if args.audio is None:
        args.out.mkdir(parents=True, exist_ok=True)
        args.audio = args.out / "sintetico.wav"
        synth_test_song(args.audio)
        print(f"\nSin archivo: audio sintético en {args.audio}")
    song_dir = args.out / args.audio.stem
    song_dir.mkdir(parents=True, exist_ok=True)
    duration = sf.info(str(args.audio)).duration
    print(f"\nCanción: {args.audio.name}  ({duration:.1f} s)")

    # --- Demucs ---
    t = time.perf_counter()
    separator = Separator(model="htdemucs_6s", device="cuda")
    load_s = time.perf_counter() - t
    torch.cuda.reset_peak_memory_stats()
    t = time.perf_counter()
    _, stems = separator.separate_audio_file(args.audio)
    torch.cuda.synchronize()
    sep_s = time.perf_counter() - t
    vram = torch.cuda.max_memory_allocated() / 2**30
    print(f"\nDemucs htdemucs_6s: carga {load_s:.1f} s, separación {sep_s:.1f} s "
          f"({duration / sep_s:.1f}x tiempo real), VRAM pico {vram:.2f} GB")
    for name, wav in stems.items():
        audio = wav.cpu().numpy().T
        sf.write(song_dir / f"{name}.wav", audio, separator.samplerate)
        rms = float(np.sqrt(np.mean(audio**2)))
        print(f"  {name:<7} rms {rms:.4f}")

    # --- Basic Pitch sobre la guitarra ---
    t = time.perf_counter()
    bp_model = cuda_basic_pitch_model()
    providers = bp_model.model.get_providers() if hasattr(bp_model.model, "get_providers") else ["?"]
    t_load = time.perf_counter() - t
    t = time.perf_counter()
    _, midi, notes = predict(song_dir / "guitar.wav", bp_model)
    bp_s = time.perf_counter() - t
    midi.write(str(song_dir / "guitar.mid"))
    print(f"\nBasic Pitch (proveedor {providers[0]}): carga {t_load:.1f} s, inferencia {bp_s:.1f} s, "
          f"{len(notes)} notas")
    for start, end, pitch, amp, _ in sorted(notes)[:10]:
        print(f"  {int(start * 1000):>7} ms  dur {int((end - start) * 1000):>5} ms  midi {pitch:>3}  amp {amp:.2f}")

    ok = providers[0] == "CUDAExecutionProvider"
    print(f"\nResultado: Demucs en CUDA OK, Basic Pitch en {'CUDA OK' if ok else 'CPU (revisar)'}")
    print(f"Archivos en {song_dir}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
