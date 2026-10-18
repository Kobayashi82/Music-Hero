"""Mide cuánto va por detrás lo que se oye de la posición que dice AIMP (lo mismo que hace el juego solo al
empezar a seguir a AIMP; ver app/src/app/loopback.py).

Uso (con AIMP sonando):
    uv run --project app python tools/measure_aimp_latency.py [segundos] [veces]
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "src"))
from app.aimp import PLAYING, Aimp, PositionClock  # noqa: E402
from app.i18n import t  # noqa: E402
from app.loopback import measure  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0
    times = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    aimp = Aimp()
    if not aimp.connected() or aimp.state() != PLAYING or aimp.track() is None:
        print(t("AIMP no está sonando"))
        return 1
    track = aimp.track()
    clock = PositionClock(aimp)
    stop = threading.Event()

    def poll() -> None:
        while not stop.wait(0.004):
            clock.update()
    threading.Thread(target=poll, daemon=True).start()
    time.sleep(1.0)  # que el reloj tenga cambios con los que interpolar
    print(Path(track.file).name)
    lag = measure(track.file, clock.estimate, seconds, times, log=lambda s: print("  " + s))
    stop.set()
    print(t("retardo de AIMP: {lag:+.0f} ms", lag=lag) if lag is not None else
          t("No se pudo medir (¿hay otro sonido a la vez, o un ecualizador fuerte en AIMP?)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
