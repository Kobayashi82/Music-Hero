"""Ajustes del juego en %APPDATA%/MusicHero/config.json (los que falten toman el valor por defecto)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

CONFIG_FILE = Path(os.environ.get("APPDATA", Path.home())) / "MusicHero" / "config.json"


@dataclass
class Config:
    audio_offset_ms: float = 0.0  # >0 si lo que oyes llega más tarde de lo que cree el reproductor
    video_offset_ms: float = 0.0  # >0 si la pantalla muestra las cosas más tarde (retardo del monitor)
    difficulty: str = "expert"
    note_speed: float = 1.0  # 1 = una nota tarda 1,2 s del horizonte a la línea
    highway_width: int = 560  # px de ancho en la línea de golpeo
    position: str = "center"  # center | left | right
    opacity: float = 0.95  # del fondo de la autopista
    volume: float = 1.0
    lyrics: bool = True  # letra bajo la autopista (sube la autopista para dejarle sitio)

    @classmethod
    def load(cls) -> Config:
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    def save(self) -> None:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
