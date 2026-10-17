"""Prueba automática de la grabadora de ritmo (app/src/app/tap.py) con AIMP.

Uso (AIMP abierto; suena música unos segundos y luego lo deja como estaba):
    uv run --project app python tools/autotest_tap.py

Pone a sonar la canción actual de AIMP en el segundo 30, arranca `tap` guardando
en una carpeta temporal, inyecta Espacio con un patrón conocido (ta ta taaaa) en
una ventana de prueba propia, retrocede para rehacer un trozo y compara los
toques guardados con la posición de AIMP medida aquí en cada pulsación.
"""

import ctypes
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app" / "src"))
from app.aimp import CMD_PAUSE, CMD_PLAY, PAUSED, PLAYING, Aimp, PositionClock  # noqa: E402

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
VK_SPACE, VK_CONTROL, VK_MENU, KEYUP = 0x20, 0x11, 0x12, 0x2

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
app = QApplication(sys.argv)
box = QLineEdit()
box.setWindowTitle("Music Hero - prueba de la grabadora (se cierra sola)")
box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
box.setGeometry(60, 60, 420, 40)
box.show()
hwnd = int(box.winId())

aimp = Aimp()
assert aimp.connected(), "AIMP no está abierto"
clock = PositionClock(aimp)


def pump(seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        clock.update()
        time.sleep(0.002)


def take_focus() -> bool:
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None)
    me = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(me, fg_thread, True)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.AttachThreadInput(me, fg_thread, False)
    box.activateWindow()
    pump(0.3)
    return user32.GetForegroundWindow() == hwnd


def key(vk: int, up: bool = False) -> float:
    if user32.GetForegroundWindow() != hwnd:
        raise SystemExit("ABORTO: la ventana de prueba perdió el foco; no inyecto nada más")
    user32.keybd_event(vk, 0, KEYUP if up else 0, 0)
    return time.perf_counter()


def tap(hold: float) -> tuple[int, int]:
    """Inyecta Espacio y devuelve la posición de AIMP (según este proceso) al pulsar y al soltar."""
    t0 = key(VK_SPACE)
    start = clock.estimate(t0)
    pump(hold)
    t1 = key(VK_SPACE, True)
    return start, clock.estimate(t1)


orig_track = aimp.track()
orig_pos, orig_state = aimp.position(), aimp.state()
tmp = Path(tempfile.mkdtemp(prefix="music_hero_taps_"))
results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(("OK   " if ok else "FALLA"), name, detail)


proc = None
try:
    if not take_focus():
        raise SystemExit("ABORTO: no consigo el foco para la ventana de prueba")
    aimp.seek(30000)
    aimp.command(CMD_PLAY)
    pump(1.0)
    check("AIMP sonando", aimp.state() == PLAYING)

    env = dict(os.environ, MUSIC_HERO_TAPS_DIR=str(tmp), PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([str(ROOT / "app" / ".venv" / "Scripts" / "tap.exe")], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(target=lambda: [lines.put(l.rstrip()) for l in proc.stdout], daemon=True).start()
    pump(1.5)

    expected = []
    # ta ta taaaa, tres veces, al ritmo de ~120 BPM
    for _ in range(3):
        for hold, gap in ((0.08, 0.17), (0.08, 0.17), (0.6, 0.4)):
            expected.append(tap(hold))
            pump(gap)
    # Rehacer: volver 2 s atrás y marcar dos toques nuevos.
    back = clock.estimate() - 2000
    aimp.seek(back)
    pump(0.8)
    expected = [e for e in expected if e[0] < back]
    for hold, gap in ((0.08, 0.3), (0.5, 0.3)):
        expected.append(tap(hold))
        pump(gap)

    t_quit = time.perf_counter()
    for vk in (VK_CONTROL, VK_MENU, ord("Q")):
        key(vk)
    pump(0.03)
    for vk in (ord("Q"), VK_MENU, VK_CONTROL):
        key(vk, True)
    proc.wait(timeout=15)
    out = []
    while not lines.empty():
        out.append(lines.get())
    print("\n".join("   | " + l for l in out))

    files = list(tmp.glob("*.json"))
    check("se guarda un archivo de toques", len(files) == 1)
    data = json.loads(files[0].read_text(encoding="utf-8"))
    got = data["taps"]
    check("número de toques (con el trozo rehecho)", len(got) == len(expected), f"{len(got)} vs {len(expected)}")
    if len(got) == len(expected):
        errs = [g[0] - e[0] for g, e in zip(got, expected)]
        derr = [(g[1] - g[0]) - (e[1] - e[0]) for g, e in zip(got, expected)]
        print(f"   error de inicio (ms): {errs}")
        print(f"   error de duración (ms): {derr}")
        check("inicios a menos de 15 ms", max(abs(e) for e in errs) <= 15)
        check("duraciones a menos de 20 ms", max(abs(d) for d in derr) <= 20)
        longs = [g for g in got if g[1] - g[0] >= 400]
        check("las notas largas se distinguen", len(longs) == sum(1 for e in expected if e[1] - e[0] >= 400))
    check("el Espacio no llegó a la ventana con foco", box.text() == "")
finally:
    if proc and proc.poll() is None:
        proc.terminate()
    # Restaurar AIMP
    for _ in range(5):
        s = aimp.state()
        if s == orig_state or (orig_state != PLAYING and s == PAUSED):
            break
        aimp.command(CMD_PLAY if s == 0 else CMD_PAUSE)
        time.sleep(0.25)
    aimp.seek(orig_pos)
    time.sleep(0.2)
    now_track = aimp.track()
    print(f"\nAIMP restaurado: {Path(now_track.file).name if now_track else '?'} @ {aimp.position()} ms, estado {aimp.state()}")

print(f"\n{sum(results)}/{len(results)} comprobaciones OK")
