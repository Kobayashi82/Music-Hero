"""Acelerómetro del Wiimote metido en la guitarra: para saber qué eje sigue al mástil (star power al levantarla).

Enseña la gravedad en cada eje (en g) y, al acabar, cuánto ha cambiado cada uno entre la postura normal y la
guitarra levantada. Uso (con el juego cerrado, que usa el mismo mando):
    uv run --project app python tools/poc_wii_tilt.py [segundos]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "src"))
from app.wii_guitar import WiiGuitar  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 25
    g = WiiGuitar.open(accel=True)
    print(f"calibración {g.calib}; guitarra: {g.is_guitar}")
    print("Sostén la guitarra como para tocar. Cuando lo pida, levanta el mástil (como en Guitar Hero) y bájalo.")
    t0, last, rows = time.time(), 0.0, []
    while time.time() - t0 < seconds:
        s = g.poll(20)
        if s is None:
            continue
        rows.append((time.time() - t0, s.accel))
        if time.time() - last > 0.25:
            last = time.time()
            el = time.time() - t0
            phase = "postura normal" if el < 8 else "¡LEVANTA el mástil!" if el < 16 else "vuelve a la postura normal"
            x, y, z = s.accel
            print(f"{el:5.1f} s  x {x:+.2f}  y {y:+.2f}  z {z:+.2f}   {phase}")
    g.close()
    mean = lambda a, b: [sum(r[1][i] for r in rows if a <= r[0] < b) / max(1, sum(a <= r[0] < b for r in rows))  # noqa: E731
                         for i in range(3)]
    normal, up = mean(2, 7), mean(11, 15)
    print("media normal  ", " ".join(f"{v:+.2f}" for v in normal))
    print("media levantada", " ".join(f"{v:+.2f}" for v in up))
    print("cambio        ", " ".join(f"{u - n:+.2f}" for n, u in zip(normal, up)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
