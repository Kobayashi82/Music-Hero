"""Separación en pistas con Demucs htdemucs_6s. Los stems se guardan en FLAC para no repetirla."""

from pathlib import Path

import soundfile as sf

from .model import STEMS

MODEL = "htdemucs_6s"


def stem_paths(out_dir: Path) -> dict[str, Path]:
    return {s: out_dir / f"{s}.flac" for s in STEMS}


def separate(audio: Path, out_dir: Path, device: str = "cuda") -> dict[str, Path]:
    paths = stem_paths(out_dir)
    if all(p.exists() for p in paths.values()):
        return paths

    import torch
    from demucs.api import Separator

    out_dir.mkdir(parents=True, exist_ok=True)
    separator = Separator(model=MODEL, device=device)
    _, stems = separator.separate_audio_file(audio)
    for name, wav in stems.items():
        data = wav.cpu().numpy().T.clip(-1, 1)
        sf.write(paths[name], data, separator.samplerate, subtype="PCM_16")
    del separator, stems
    if device == "cuda":
        torch.cuda.empty_cache()
    return paths
