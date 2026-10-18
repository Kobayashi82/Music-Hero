"""Biblioteca de canciones con chart (out/charts), agrupada en artista -> álbum -> canción. Sin Qt.

El grupo sale sobre todo de las carpetas (Musicas/Artista/Álbum/canción.mp3), que es como está ordenada la
música: así "Queen & David Bowie" sigue dentro de Queen. Los prefijos numéricos de carpetas y archivos
("1 - Let Go", "02 - Complicated") dan el orden y se quitan del nombre. Si la canción no está en
Artista/Álbum/, se usan las etiquetas que guardó el generador en la chart.

El índice se guarda en %APPDATA%/MusicHero/library.json y solo se relee la chart que haya cambiado.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from .chart import CHARTS_DIR
from .config import CONFIG_FILE

LIBRARY_FILE = CONFIG_FILE.parent / "library.json"
_PREFIX = re.compile(r"^\s*(\d+)\s*[-.)_]\s*")
NO_ALBUM = "(sin álbum)"
NO_ARTIST = "(sin artista)"


@dataclass
class Entry:
    folder: str  # carpeta de la chart
    audio: str
    sha: str
    title: str
    artist: str  # tal como lo dice la etiqueta
    album: str
    duration_ms: int

    # agrupación (se calcula con group())
    group_artist: str = ""
    group_album: str = ""
    album_order: int = 0
    track: int = 0


def split_prefix(name: str) -> tuple[int | None, str]:
    """'02 - Complicated' -> (2, 'Complicated')."""
    m = _PREFIX.match(name)
    return (int(m.group(1)), name[m.end():].strip()) if m else (None, name.strip())


def scan(charts_dir: Path = CHARTS_DIR, cache_file: Path = LIBRARY_FILE) -> list[Entry]:
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    out, fresh = [], {}
    for chart in sorted(charts_dir.glob("*/chart.json")):
        key = str(chart.parent)
        try:
            mtime = chart.stat().st_mtime
        except OSError:
            continue
        hit = cache.get(key)
        if hit and hit.get("mtime") == mtime:
            entry = Entry(**hit["entry"])
        else:
            try:
                song = json.loads(chart.read_text(encoding="utf-8"))["song"]
            except (OSError, ValueError, KeyError):
                continue
            entry = Entry(key, song.get("audio_file", ""), song.get("audio_sha256", ""), song.get("title", ""),
                          song.get("artist", ""), song.get("album", ""), int(song.get("duration_ms", 0)))
        fresh[key] = {"mtime": mtime, "entry": asdict(entry)}
        out.append(entry)
    if fresh != cache:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return [e for e in out if e.audio and os.path.exists(e.audio)]


def group(entries: list[Entry]) -> dict[str, dict[str, list[Entry]]]:
    """{artista: {álbum: [canciones]}}, todo ya ordenado (artistas por nombre, álbumes y pistas por su
    número o, si no tienen, por nombre)."""
    if not entries:
        return {}
    try:
        root = Path(os.path.commonpath([str(Path(e.audio).parent) for e in entries]))
    except ValueError:  # discos distintos
        root = None
    for e in entries:
        path = Path(e.audio)
        parts = path.relative_to(root).parts if root and path.is_relative_to(root) else (path.name,)
        num, name = split_prefix(path.stem)
        e.track = num if num is not None else 0
        if len(parts) >= 3:  # Artista/Álbum/canción
            e.group_artist = parts[0]
            order, e.group_album = split_prefix(parts[-2])
            e.album_order = order if order is not None else 0
        elif len(parts) == 2:  # Artista/canción
            e.group_artist, e.group_album = parts[0], e.album or NO_ALBUM
        else:
            e.group_artist, e.group_album = e.artist or NO_ARTIST, e.album or NO_ALBUM
        if not e.title:
            e.title = name
    tree: dict[str, dict[str, list[Entry]]] = {}
    for e in entries:
        tree.setdefault(e.group_artist, {}).setdefault(e.group_album, []).append(e)
    out = {}
    for artist in sorted(tree, key=str.casefold):
        albums = tree[artist]
        ordered = sorted(albums, key=lambda a: (albums[a][0].album_order or 10**6, a.casefold()))
        out[artist] = {a: sorted(albums[a], key=lambda e: (e.track or 10**6, e.title.casefold())) for a in ordered}
    return out


def fold(text: str) -> str:
    """Para buscar: sin mayúsculas ni tildes («Canción» -> «cancion»)."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def search(entries: list[Entry], query: str, limit: int = 50) -> list[Entry]:
    """Canciones con todas las palabras en el título, el artista o el álbum. Primero las que empiezan por
    lo buscado, luego las que lo tienen todo en el título y luego el resto."""
    q = fold(query).strip()
    words = q.split()
    if not words:
        return []
    found = []
    for e in entries:
        title = fold(e.title)
        hay = " ".join((title, fold(e.group_artist or e.artist), fold(e.artist), fold(e.group_album or e.album)))
        if all(w in hay for w in words):
            rank = 0 if title.startswith(q) else 1 if all(w in title for w in words) else 2
            found.append((rank, title, fold(e.group_artist), e))
    found.sort(key=lambda r: r[:3])
    return [r[3] for r in found[:limit]]
