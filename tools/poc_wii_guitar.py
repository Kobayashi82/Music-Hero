"""Fase 0 - Guitarra de Wii leída por HID (app/src/app/wii_guitar.py), sin SDL.

Uso:
    uv run --project app python tools/poc_wii_guitar.py

Antes: Wiimote emparejado (tools/pair_wiimote.py) y la guitarra enchufada. Pulsa cada traste, el strum
arriba y abajo, Start/Select y mueve la palanca. Luego haz clic en otra ventana y sigue tocando: no hace
falta foco. Cada cambio sale con los 6 bytes en crudo de la extensión.
"""

import sys
import time

from app.wii_guitar import FRETS, WiiGuitar


def show(s) -> str:
    parts = [f for f, on in zip(FRETS, s.frets) if on]
    if s.strum_up:
        parts.append("STRUM ARRIBA")
    if s.strum_down:
        parts.append("STRUM ABAJO")
    if s.start:
        parts.append("start")
    if s.select:
        parts.append("select")
    if s.whammy > 0.05:
        parts.append(f"palanca {s.whammy:.2f}")
    if abs(s.stick[0]) > 0.3 or abs(s.stick[1]) > 0.3:
        parts.append(f"joystick {s.stick[0]:+.1f},{s.stick[1]:+.1f}")
    if s.wiimote:
        parts.append(f"wiimote {s.wiimote:04x}")
    return " + ".join(parts) or "(nada)"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    g = WiiGuitar.open()
    ext = g.extension.hex(" ") if g.extension else "ninguna"
    print(f"Wiimote abierto. Extensión: {ext}" + (" (guitarra)" if g.is_guitar else " (¡no es la guitarra!)"))
    print("Toca. Ctrl+C para salir.\n")
    t0, last, n, rate_t, rate_n = time.perf_counter(), None, 0, time.perf_counter(), 0
    try:
        while True:
            s = g.poll(50)
            if s is None:
                continue
            n += 1
            rate_n += 1
            key = (s.frets, s.strum_up, s.strum_down, s.start, s.select, round(s.whammy, 1),
                   round(s.stick[0], 1), round(s.stick[1], 1), s.wiimote)
            if key != last:
                ms = int((time.perf_counter() - t0) * 1000)
                print(f"{ms:8d} ms  [{s.raw.hex(' ')}]  {show(s)}")
                last = key
            if time.perf_counter() - rate_t > 10:
                print(f"          ({rate_n / (time.perf_counter() - rate_t):.0f} informes/s)")
                rate_t, rate_n = time.perf_counter(), 0
    except KeyboardInterrupt:
        pass
    finally:
        g.close()
    print(f"\n{n} informes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
