"""Diagnóstico de la guitarra de Wii: lo que manda por HID (app/src/app/wii_guitar.py), cambio a cambio.

Uso:
    uv run --project app python tools/wii_guitar_monitor.py

Antes: Wiimote emparejado (tools/pair_wiimote.py o Ajustes → Guitarra y teclas) y la guitarra enchufada, con el
juego cerrado (usa el mismo mando). Pulsa cada traste, el strum, Start/Select y mueve la palanca: cada cambio
sale con los 6 bytes en crudo de la extensión. Sirve para ver si algún botón no llega o llega cambiado.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "src"))
from app.i18n import t  # noqa: E402
from app.wii_guitar import FRETS, WiiGuitar  # noqa: E402


def show(s) -> str:
    parts = [f for f, on in zip(FRETS, s.frets) if on]
    if s.strum_up:
        parts.append(t("STRUM ARRIBA"))
    if s.strum_down:
        parts.append(t("STRUM ABAJO"))
    if s.start:
        parts.append("start")
    if s.select:
        parts.append("select")
    if s.whammy > 0.05:
        parts.append(t("palanca {v:.2f}", v=s.whammy))
    if abs(s.stick[0]) > 0.3 or abs(s.stick[1]) > 0.3:
        parts.append(f"joystick {s.stick[0]:+.1f},{s.stick[1]:+.1f}")
    if s.wiimote:
        parts.append(f"wiimote {s.wiimote:04x}")
    return " + ".join(parts) or t("(nada)")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    g = WiiGuitar.open()
    ext = g.extension.hex(" ") if g.extension else t("ninguna")
    print(t("Wiimote abierto. Extensión: {ext}", ext=ext) + " "
          + (t("(guitarra)") if g.is_guitar else t("(¡no es la guitarra!)")))
    print(t("Toca. Ctrl+C para salir.") + "\n")
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
                print("          " + t("({n:.0f} informes/s)", n=rate_n / (time.perf_counter() - rate_t)))
                rate_t, rate_n = time.perf_counter(), 0
    except KeyboardInterrupt:
        pass
    finally:
        g.close()
    print("\n" + t("{n} informes", n=n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
