"""Lectura de audio, hash y etiquetas."""

import hashlib
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

from .model import SongInfo


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_mono(path: Path, sr: int) -> np.ndarray:
    data, file_sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if file_sr != sr:
        mono = soxr.resample(mono, file_sr, sr)
    return mono


def song_info(path: Path) -> SongInfo:
    title = artist = album = ""
    try:
        import mutagen

        tags = mutagen.File(str(path), easy=True)
        if tags is not None:
            title = (tags.get("title") or [""])[0]
            artist = (tags.get("artist") or [""])[0]
            album = (tags.get("album") or [""])[0]
    except Exception:
        pass
    if not title:
        # "Artista - Título.mp3"
        stem = path.stem
        if " - " in stem:
            artist_guess, title = stem.split(" - ", 1)
            artist = artist or artist_guess
        else:
            title = stem
    duration_ms = int(round(sf.info(str(path)).duration * 1000))
    return SongInfo(title.strip(), artist.strip(), album.strip(), duration_ms, sha256_file(path), str(path))
