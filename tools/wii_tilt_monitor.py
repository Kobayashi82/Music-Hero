"""Diagnóstico del star power: el acelerómetro del Wiimote metido en la guitarra, para ver qué eje sigue al mástil
y reajustar el umbral si hiciera falta (app/src/app/starpower.py, hoy eje Y ≤ −0,65 g).

Enseña la gravedad en cada eje (en g) y, al acabar, cuánto ha cambiado cada uno entre la postura normal y la
guitarra levantada; y avisa cuando el juego la daría por levantada (starpower.Tilt). Uso (con el juego cerrado,
que usa el mismo mando):
    uv run --project app python tools/wii_tilt_monitor.py [segundos]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "src"))
from app.i18n import t  # noqa: E402
from app.starpower import Tilt  # noqa: E402
from app.wii_guitar import WiiGuitar  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 25
    g = WiiGuitar.open(accel=True)
    print(t("calibración {calib}; guitarra: {guitar}", calib=g.calib, guitar=g.is_guitar))
    print(t("Sostén la guitarra como para tocar. Cuando lo pida, levanta el mástil (como en Guitar Hero) y bájalo."))
    t0, last, rows, tilt = time.time(), 0.0, [], Tilt()
    while time.time() - t0 < seconds:
        s = g.poll(20)
        if s is None:
            continue
        rows.append((time.time() - t0, s.accel))
        if tilt.feed(s.accel):
            print(f"{time.time() - t0:5.1f} s  >>> " + t("el juego la da por levantada: star power"))
        if time.time() - last > 0.25:
            last = time.time()
            el = time.time() - t0
            phase = (t("postura normal") if el < 8 else t("¡LEVANTA el mástil!") if el < 16
                     else t("vuelve a la postura normal"))
            x, y, z = s.accel
            print(f"{el:5.1f} s  x {x:+.2f}  y {y:+.2f}  z {z:+.2f}   {phase}")
    g.close()
    mean = lambda a, b: [sum(r[1][i] for r in rows if a <= r[0] < b) / max(1, sum(a <= r[0] < b for r in rows))  # noqa: E731
                         for i in range(3)]
    normal, up = mean(2, 7), mean(11, 15)
    print(f"{t('media normal'):<16}", " ".join(f"{v:+.2f}" for v in normal))
    print(f"{t('media levantada'):<16}", " ".join(f"{v:+.2f}" for v in up))
    print(f"{t('cambio'):<16}", " ".join(f"{u - n:+.2f}" for n, u in zip(normal, up)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
