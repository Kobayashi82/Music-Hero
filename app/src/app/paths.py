"""Dónde está cada cosa: en el repositorio (desarrollo) o instalado (PyInstaller, fase 7).

Instalado, lo grande va a %LOCALAPPDATA%/MusicHero (charts, el motor con sus modelos, la cola); los ajustes,
récords e índice siguen en %APPDATA%/MusicHero (config.py). MUSICHERO_HOME cambia la carpeta de lo grande
(para probar una instalación limpia sin tocar la de verdad).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
REPO = Path(__file__).resolve().parents[3]  # solo tiene sentido en desarrollo
HOME = Path(os.environ.get("MUSICHERO_HOME") or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MusicHero")
DATA = HOME if FROZEN or os.environ.get("MUSICHERO_HOME") else REPO / "out"

CHARTS_DIR = DATA / "charts"
ENGINE_DIR = HOME / "engine"  # el motor instalado (Python, torch, modelos); en desarrollo no se usa
QUEUE_FILE = DATA / "engine_queue.json"
ENGINE_LOG = DATA / "engine.log"
APP_LOG = DATA / "app.log"  # instalada no hay consola: lo que imprime la app va aquí
MODEL = ENGINE_DIR / "models" / "best.pt" if FROZEN else REPO / "models" / "best.pt"
