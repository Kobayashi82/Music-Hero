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


def wrapped_mp3(path: Path) -> bool:
    """MP3 metido en un contenedor WAV (con etiqueta ID3 delante): libsndfile solo lee un trozo y
    el cargador de Demucs no lo abre. ffmpeg lo lee entero si se le fuerza el formato mp3."""
    try:
        return path.suffix.lower() == ".mp3" and sf.info(str(path)).format == "WAV"
    except Exception:  # noqa: BLE001
        return False


def load_mono(path: Path, sr: int) -> np.ndarray:
    if wrapped_mp3(path):
        return _ffmpeg_mono(path, sr, fmt="mp3")
    try:
        data, file_sr = sf.read(str(path), dtype="float32", always_2d=True)
    except sf.LibsndfileError:
        return _ffmpeg_mono(path, sr)  # algunos .opus que libsndfile no entiende
    mono = data.mean(axis=1)
    if file_sr != sr:
        mono = soxr.resample(mono, file_sr, sr)
    return mono


def _ffmpeg_mono(path: Path, sr: int, fmt: str | None = None) -> np.ndarray:
    return ffmpeg_decode(path, sr, 1, fmt)[:, 0]


def ffmpeg_decode(path: Path, sr: int, channels: int, fmt: str | None = None) -> np.ndarray:
    """(muestras, canales) float32. fmt fuerza el formato de entrada (p. ej. 'mp3')."""
    import subprocess

    cmd = ["ffmpeg", "-v", "error"] + (["-f", fmt] if fmt else []) + ["-i", str(path), "-ac", str(channels),
                                                                     "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, channels).copy()


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
