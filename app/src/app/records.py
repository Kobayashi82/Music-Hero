"""Récords y estadísticas por canción, y la dificultad elegida en cada una, en %APPDATA%/MusicHero/stats.json.

Las canciones van por el hash de su audio (no cambia aunque se mueva o renombre el archivo). Por canción:
la última dificultad elegida y, por dificultad, partidas jugadas, la mejor (por puntos), la mejor precisión,
la mejor racha y las últimas HISTORY partidas. Sin Qt.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .config import CONFIG_FILE

STATS_FILE = CONFIG_FILE.parent / "stats.json"
HISTORY = 20


@dataclass
class Play:
    score: int
    accuracy: float  # 0..1
    hits: int
    total: int
    best_streak: int
    overstrums: int
    date: str = ""  # ISO, se pone al guardar

    @property
    def full_combo(self) -> bool:
        return self.total > 0 and self.hits == self.total


class Records:
    def __init__(self, path: Path = STATS_FILE):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("version", 1)
        self.data.setdefault("songs", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)  # sin dejar el archivo a medias si se corta

    def _song(self, sha: str, title: str = "", artist: str = "") -> dict:
        song = self.data["songs"].setdefault(sha, {})
        if title:
            song["title"], song["artist"] = title, artist
        return song

    # ---------- dificultad por canción ----------

    def difficulty(self, sha: str) -> str | None:
        return self.data["songs"].get(sha, {}).get("difficulty")

    def set_difficulty(self, sha: str, difficulty: str, title: str = "", artist: str = "") -> None:
        self._song(sha, title, artist)["difficulty"] = difficulty
        self.save()

    # ---------- partidas ----------

    def stats(self, sha: str, difficulty: str) -> dict:
        """{"plays", "best", "best_accuracy", "best_streak", "history"}; vacío si no hay partidas."""
        return self.data["songs"].get(sha, {}).get("plays", {}).get(difficulty, {})

    def best(self, sha: str, difficulty: str) -> Play | None:
        b = self.stats(sha, difficulty).get("best")
        return Play(**b) if b else None

    def add_play(self, sha: str, difficulty: str, play: Play, title: str = "", artist: str = "",
                 when: datetime | None = None) -> Play | None:
        """Guarda la partida. Devuelve el récord anterior si esta lo supera (o un Play vacío si era la
        primera), y None si no lo supera."""
        play.date = (when or datetime.now()).isoformat(timespec="seconds")
        st = self._song(sha, title, artist).setdefault("plays", {}).setdefault(difficulty, {})
        st["plays"] = st.get("plays", 0) + 1
        prev = Play(**st["best"]) if st.get("best") else None
        record = prev is None or play.score > prev.score
        if record:
            st["best"] = asdict(play)
        st["best_accuracy"] = max(st.get("best_accuracy", 0.0), play.accuracy)
        st["best_streak"] = max(st.get("best_streak", 0), play.best_streak)
        st["history"] = (st.get("history", []) + [asdict(play)])[-HISTORY:]
        self.save()
        if not record:
            return None
        return prev or Play(0, 0.0, 0, 0, 0, 0)
