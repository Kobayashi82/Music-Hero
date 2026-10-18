"""Empareja un Wiimote con Windows sin escribir PIN (Windows 11 lo pide y no se puede teclear).

La lógica está en app/src/app/pairing.py (la usa también el juego: Ajustes → «Emparejar la guitarra de Wii»).

Uso:
    uv run --project app python tools/pair_wiimote.py

1. Arranca el script y pulsa el botón rojo de sync del Wiimote (bajo la tapa de las pilas).
2. Si deja de parpadear antes de que salga, vuelve a pulsarlo: el script sigue buscando 2 minutos.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "src"))
from app.pairing import pair  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    return 0 if pair(print) else 1


if __name__ == "__main__":
    sys.exit(main())
