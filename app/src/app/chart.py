"""Charts del generador (shared/chart_schema.json, v1 y v2): cargar y encontrar la de un audio."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .paths import CHARTS_DIR
DIFFS = ("expert", "hard", "medium", "easy")
DIFF_NAMES = {"expert": "Experto", "hard": "Difícil", "medium": "Medio", "easy": "Fácil"}


@dataclass
class Note:
    time_ms: int
    frets: tuple[int, ...]  # 0 verde .. 4 naranja
    sustain_ms: int = 0
    hopo: bool = False


@dataclass
class Chart:
    title: str
    artist: str
    audio_file: Path
    audio_sha256: str
    duration_ms: int
    beats: list[tuple[int, bool]]  # (ms, inicio de compás)
    difficulties: dict[str, list[Note]]
    folder: Path
    star_power: dict[str, list[tuple[int, int]]] = field(default_factory=dict)  # (inicio, fin) ms; v2, si las trae

    @classmethod
    def load(cls, path: Path) -> Chart:
        """path: chart.json o su carpeta."""
        if path.is_dir():
            path = path / "chart.json"
        d = json.loads(path.read_text(encoding="utf-8"))
        song = d["song"]
        diffs, star = {}, {}
        for name in DIFFS:
            track = d["difficulties"].get(name, {})
            notes = track.get("notes", [])
            if notes:
                diffs[name] = [Note(int(n["time_ms"]), tuple(sorted(n["frets"])), int(n.get("sustain_ms", 0)),
                                    bool(n.get("hopo", False))) for n in notes]
                if track.get("star_power"):
                    star[name] = [(int(p["time_ms"]), int(p["time_ms"]) + int(p["length_ms"])) for p in track["star_power"]]
        return cls(song["title"], song["artist"], Path(song["audio_file"]), song["audio_sha256"],
                   int(song["duration_ms"]), [(int(b["time_ms"]), bool(b.get("downbeat"))) for b in d.get("beats", [])],
                   diffs, path.parent, star)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def find_chart(audio: Path, charts_dir: Path = CHARTS_DIR) -> Path | None:
    """Carpeta de la chart de este audio: primero por nombre (out/charts/<nombre>), luego por hash."""
    sha = sha256_file(audio)
    name = audio.stem.rstrip(" .")
    candidates = [charts_dir / name, charts_dir / f"{name} ({sha[:8]})"]
    candidates += [p for p in charts_dir.glob("*") if p not in candidates]
    for folder in candidates:
        f = folder / "chart.json"
        if not f.exists():
            continue
        try:
            if json.loads(f.read_text(encoding="utf-8"))["song"]["audio_sha256"] == sha:
                return folder
        except (OSError, ValueError, KeyError):
            continue
    return None
