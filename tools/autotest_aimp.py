"""Prueba automática de la API remota de AIMP: precisión de la posición, seek,
cambio de pista. Deja AIMP como estaba (pista, posición, pausa).

Uso (AIMP abierto; hace sonar música unos segundos):
    uv run --project app python tools/autotest_aimp.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from poc_aimp import (PROP_DURATION, PROP_POSITION, PROP_STATE, REMOTE_CLASS,  # noqa: E402
                      WM_AIMP_PROPERTY, get_prop, read_track, user32)

WM_AIMP_COMMAND = 0x0400 + 0x75
CMD_PLAY, CMD_PAUSE, CMD_NEXT, CMD_PREV = 13, 15, 17, 18
PROP_SET = 1

hwnd = user32.FindWindowW(REMOTE_CLASS, None)
assert hwnd, "AIMP no está abierto"
cmd = lambda c: user32.SendMessageW(hwnd, WM_AIMP_COMMAND, c, 0)
seek = lambda ms: user32.SendMessageW(hwnd, WM_AIMP_PROPERTY, PROP_POSITION | PROP_SET, ms)
pos = lambda: get_prop(hwnd, PROP_POSITION)
state = lambda: get_prop(hwnd, PROP_STATE)

orig_file = read_track()["FileName"]
orig_pos, orig_state = pos(), state()
print(f"Inicial: {Path(orig_file).name} @ {orig_pos} ms, estado {orig_state}")

try:
    # 1. Granularidad de la posición mientras suena
    seek(30000)
    cmd(CMD_PLAY)
    time.sleep(0.5)
    samples = []
    t_end = time.perf_counter() + 4
    while time.perf_counter() < t_end:
        samples.append((time.perf_counter(), pos()))
        time.sleep(0.002)
    changes = [(t, p) for (t, p), (_, q) in zip(samples[1:], samples) if p != q]
    steps = [b[1] - a[1] for a, b in zip(changes, changes[1:])]
    gaps = [(b[0] - a[0]) * 1000 for a, b in zip(changes, changes[1:])]
    # deriva: posición AIMP vs reloj en todo el tramo
    (t0, p0), (t1, p1) = samples[0], samples[-1]
    print(f"\n1) Sonando 4 s: {len(samples)} lecturas, la posición cambió {len(changes)} veces")
    if steps:
        print(f"   paso típico {sorted(steps)[len(steps)//2]} ms (mín {min(steps)}, máx {max(steps)}), "
              f"cada {sorted(gaps)[len(gaps)//2]:.1f} ms de reloj")
    print(f"   avance AIMP {p1 - p0} ms vs reloj {int((t1 - t0) * 1000)} ms")
    # residuo frente a una recta (jitter de la posición reportada)
    resid = [p - (p0 + (t - t0) * 1000) for t, p in samples]
    print(f"   desviación respecto al reloj: mín {min(resid):.0f} ms, máx {max(resid):.0f} ms")

    # 2. Latencia del seek
    t = time.perf_counter()
    seek(90000)
    while abs(pos() - 90000) > 500 and time.perf_counter() - t < 2:
        time.sleep(0.001)
    print(f"\n2) Seek a 1:30 reflejado en {(time.perf_counter() - t) * 1000:.0f} ms (pos {pos()})")

    # 3. Pausa
    cmd(CMD_PAUSE)
    time.sleep(0.2)
    a = pos(); time.sleep(0.5); b = pos()
    print(f"\n3) Pausa: estado {state()}, posición quieta: {a == b} ({a} -> {b})")

    # 4. Cambio de pista
    cmd(CMD_PLAY)
    t = time.perf_counter()
    cmd(CMD_NEXT)
    while read_track()["FileName"] == orig_file and time.perf_counter() - t < 3:
        time.sleep(0.005)
    tr = read_track()
    print(f"\n4) Siguiente pista detectada en {(time.perf_counter() - t) * 1000:.0f} ms: "
          f"{Path(tr['FileName']).name}, pos {pos()}, dur {get_prop(hwnd, PROP_DURATION)}")
    time.sleep(1)
finally:
    # Restaurar: volver a la pista original (PREV puede reiniciar la actual, por eso se reintenta)
    for _ in range(4):
        if read_track()["FileName"] == orig_file:
            break
        cmd(CMD_PREV)
        t = time.perf_counter()
        while read_track()["FileName"] != orig_file and time.perf_counter() - t < 1:
            time.sleep(0.01)
    seek(orig_pos)
    # Dejarlo en pausa (PAUSE puede alternar, así que se comprueba el estado)
    for _ in range(5):
        s = state()
        if s == orig_state or (orig_state != 2 and s == 1):
            break
        cmd(CMD_PLAY if s == 0 else CMD_PAUSE)
        time.sleep(0.25)
    seek(orig_pos)
    time.sleep(0.3)
    print(f"\nRestaurado: {Path(read_track()['FileName']).name} @ {pos()} ms, estado {state()}")
