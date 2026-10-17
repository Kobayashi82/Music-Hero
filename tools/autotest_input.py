"""Prueba automática de poc_keyboard.py y del atajo de poc_overlay_gpu.py.

Las teclas se inyectan con keybd_event teniendo el foco en una ventana de
prueba propia (con un campo de texto): si algo falla, lo que se escape cae ahí,
no en el reproductor del usuario. Si no se consigue el foco, no se inyecta nada.
Ojo: la ventana de prueba toma el foco, así que la app que lo tuviera (un
reproductor de vídeo, por ejemplo) puede reaccionar a perderlo.

Uso:
    uv run --project app python tools/autotest_input.py [captura.png]
"""
import ctypes
import queue
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit

ROOT = str(Path(__file__).resolve().parent.parent)
SHOT = sys.argv[1] if len(sys.argv) > 1 else None
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
VK_CONTROL, VK_MENU, VK_UP, VK_DOWN, VK_RETURN = 0x11, 0x12, 0x26, 0x28, 0x0D
KEYUP = 0x2

app = QApplication(sys.argv)
box = QLineEdit()
box.setWindowTitle("Music Hero - ventana de prueba (se cierra sola)")
box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
box.setGeometry(60, 60, 420, 40)
box.show()
hwnd = int(box.winId())


def pump(seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def take_focus() -> bool:
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None)
    me = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(me, fg_thread, True)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.AttachThreadInput(me, fg_thread, False)
    box.activateWindow()
    box.setFocus()
    pump(0.3)
    return user32.GetForegroundWindow() == hwnd


def key(vk: int, up: bool = False) -> None:
    if user32.GetForegroundWindow() != hwnd:
        raise SystemExit("ABORTO: la ventana de prueba perdió el foco; no inyecto nada más")
    user32.keybd_event(vk, 0, KEYUP if up else 0, 0)


def tap(vk: int, hold: float = 0.08) -> None:
    key(vk); pump(hold); key(vk, True); pump(0.05)


def combo_ctrl_alt(vk: int) -> None:
    key(VK_CONTROL); key(VK_MENU); key(vk); pump(0.03)
    key(vk, True); key(VK_MENU, True); key(VK_CONTROL, True); pump(0.1)


class Proc:
    def __init__(self, *args: str):
        self.lines: queue.Queue[str] = queue.Queue()
        self.log: list[str] = []
        self.p = subprocess.Popen([ROOT + "/app/.venv/Scripts/python.exe", "-u", *args], cwd=ROOT,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                  errors="replace")
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            self.lines.put(line.rstrip())

    def wait_for(self, text: str, timeout: float = 3.0) -> bool:
        end = time.perf_counter() + timeout
        while time.perf_counter() < end:
            try:
                line = self.lines.get_nowait()
                self.log.append(line)
                print("   |", line)
                if text in line:
                    return True
            except queue.Empty:
                pump(0.01)
        return False

    def drain(self):
        self.wait_for("\0", 0.3)

    def stop(self):
        self.p.terminate()


results = []
def check(name, ok):
    results.append((name, ok))
    print(("OK   " if ok else "FALLA"), name)


# ---------- Teclado ----------
print("== poc_keyboard.py")
kb = Proc("tools/poc_keyboard.py")
try:
    check("arranca", kb.wait_for("modo juego", 15))
    if not take_focus():
        raise SystemExit("ABORTO: no consigo el foco para la ventana de prueba")
    combo_ctrl_alt(ord("H"))
    active = kb.wait_for("ACTIVO")
    check("Ctrl+Alt+H activa el modo juego", active)
    if not active:
        raise SystemExit("ABORTO: modo juego no activo, no inyecto teclas de juego")
    kb.drain()
    check("sin avisos de teclas ocupadas", not any("AVISO" in l for l in kb.log))

    # Acorde verde+amarillo mantenido mientras se rasguea abajo
    key(ord("A")); key(ord("D")); pump(0.05)
    tap(VK_DOWN)
    pump(0.1); key(ord("A"), True); key(ord("D"), True); pump(0.05)
    for vk in (ord("S"), ord("F"), ord("G"), VK_UP, VK_RETURN):
        tap(vk)
    kb.drain()
    joined = "\n".join(kb.log)
    for name in ("verde PULSADO", "amarillo PULSADO", "strum abajo PULSADO", "verde suelto", "rojo PULSADO",
                 "azul PULSADO", "naranja PULSADO", "strum arriba PULSADO", "strum (intro) PULSADO", "naranja suelto"):
        check(f"evento: {name}", name in joined)
    check("las teclas del juego no llegan a la ventana con foco", box.text() == "")

    combo_ctrl_alt(ord("H"))
    check("Ctrl+Alt+H desactiva", kb.wait_for("desactivado"))
    tap(ord("A"))
    pump(0.2)
    check("desactivado, la A vuelve a escribir normal", box.text().lower() == "a")
    box.clear()
finally:
    kb.stop()

# ---------- Overlay ----------
print("\n== poc_overlay_gpu.py")
ov = Proc("tools/poc_overlay_gpu.py")
try:
    check("arranca", ov.wait_for("en marcha", 20))
    pump(0.5)
    check("el overlay no roba el foco", user32.GetForegroundWindow() == hwnd)
    if not take_focus():
        raise SystemExit("ABORTO: no consigo el foco")
    combo_ctrl_alt(ord("H"))
    check("Ctrl+Alt+H oculta", ov.wait_for("overlay oculto"))
    combo_ctrl_alt(ord("H"))
    check("Ctrl+Alt+H muestra", ov.wait_for("overlay visible"))
    pump(1.0)
    check("sigue sin robar el foco tras mostrarse", user32.GetForegroundWindow() == hwnd)
    if SHOT:
        app.primaryScreen().grabWindow(0).save(SHOT)
    combo_ctrl_alt(ord("Q"))
    check("Ctrl+Alt+Q sale", ov.p.wait(timeout=5) == 0)
finally:
    if ov.p.poll() is None:
        ov.stop()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} comprobaciones OK")
