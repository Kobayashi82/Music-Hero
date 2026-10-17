"""Fase 0 - Overlay: ventana transparente, sin bordes, siempre encima, que deja
pasar los clics, con notas moviéndose a 60+ fps. Se muestra/oculta con un atajo
global.

Uso:
    uv run --project app python tools/poc_overlay.py
    uv run --project app python tools/poc_overlay.py --hotkey f9 --fullscreen

Atajos (globales, funcionan sin foco):
    Ctrl+Alt+G   mostrar / ocultar  (cámbialo con --hotkey)
    Ctrl+Alt+Q   salir              (también Ctrl+C en la consola)

Qué comprobar:
    - Se ve el escritorio a través de la autopista y no tiene bordes.
    - Los clics atraviesan la ventana (puedes usar lo que hay debajo).
    - No roba el foco: escribe en otra app mientras está visible.
    - Sigue encima al cambiar de ventana.
    - El contador marca 60 fps o más (o la frecuencia de tu monitor).
"""

import argparse
import ctypes
import signal
import sys
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QElapsedTimer, QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
winmm = ctypes.windll.winmm

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x20, 0x80, 0x8000000

user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]

HOTKEY_TOGGLE, HOTKEY_QUIT = 1, 2
LANE_COLORS =["#2ecc40", "#ff4136", "#ffdc00", "#0074d9", "#ff851b"]
NOTE_TRAVEL_S = 1.6  # segundos que tarda una nota en bajar hasta la línea de golpeo


def parse_hotkey(text: str) -> tuple[int, int]:
    """'ctrl+alt+g' -> (modificadores, código de tecla virtual)."""
    mods = 0
    vk = None
    for part in text.lower().replace(" ", "").split("+"):
        if part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "alt":
            mods |= MOD_ALT
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part == "win":
            mods |= MOD_WIN
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x70 + int(part[1:]) - 1
        elif part in ("pause", "scrolllock", "insert", "home", "end", "pageup", "pagedown"):
            vk = {"pause": 0x13, "scrolllock": 0x91, "insert": 0x2D, "home": 0x24,
                  "end": 0x23, "pageup": 0x21, "pagedown": 0x22}[part]
        else:
            raise ValueError(f"tecla no reconocida: {part!r}")
    if vk is None:
        raise ValueError(f"falta la tecla en {text!r}")
    return mods | MOD_NOREPEAT, vk


class HotkeyThread(QObject):
    """RegisterHotKey en un hilo propio con su bucle de mensajes Win32.

    Las teclas se registran sin ventana (hwnd=NULL), así que WM_HOTKEY llega
    a la cola de este hilo aunque el overlay esté oculto o sin foco.
    """

    pressed = Signal(int)

    def __init__(self, hotkeys: dict[int, tuple[int, int]]):
        super().__init__()
        self._hotkeys = hotkeys
        self._thread_id = 0
        self._ready = threading.Event()
        self.errors: list[str] = []
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        self._ready.wait()

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout=1)

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        for hk_id, (mods, vk) in self._hotkeys.items():
            if not user32.RegisterHotKey(None, hk_id, mods, vk):
                self.errors.append(f"no se pudo registrar el atajo {hk_id} (¿lo usa otra app?)")
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.pressed.emit(msg.wParam)
        for hk_id in self._hotkeys:
            user32.UnregisterHotKey(None, hk_id)


class Overlay(QWidget):
    def __init__(self, fullscreen: bool):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        if fullscreen:
            self.setGeometry(geo)
        else:
            w = min(560, geo.width())
            self.setGeometry(geo.x() + (geo.width() - w) // 2, geo.y(), w, geo.height())
        self.refresh_hz = screen.refreshRate()

        self.clock = QElapsedTimer()
        self.clock.start()
        self.frame_times: list[float] = []
        self.fps = 0.0
        self.min_fps = 0.0

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(max(1, int(1000 / max(self.refresh_hz, 60))))
        self.timer.timeout.connect(self.update)

    def showEvent(self, event):
        super().showEvent(event)
        self._force_click_through()
        self.frame_times.clear()
        self.timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.timer.stop()

    def _force_click_through(self) -> None:
        """Qt ya pone estos estilos, pero los forzamos y lo comprobamos."""
        hwnd = int(self.winId())
        wanted = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if style & wanted != wanted:
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | wanted)
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        ok = style & wanted == wanted
        print(f"estilos extendidos: 0x{style:08x} -> click-through {'OK' if ok else 'FALLA'}")

    def on_hotkey(self, hk_id: int) -> None:
        if hk_id == HOTKEY_TOGGLE:
            self.toggle()
        elif hk_id == HOTKEY_QUIT:
            QApplication.quit()

    def toggle(self) -> None:
        self.setVisible(not self.isVisible())
        print("overlay", "visible" if self.isVisible() else "oculto")

    def paintEvent(self, event):
        now = self.clock.nsecsElapsed() / 1e9
        self.frame_times.append(now)
        while self.frame_times and now - self.frame_times[0] > 1.0:
            self.frame_times.pop(0)
        if len(self.frame_times) > 1:
            self.fps = (len(self.frame_times) - 1) / (self.frame_times[-1] - self.frame_times[0])
            gaps = [b - a for a, b in zip(self.frame_times, self.frame_times[1:])]
            self.min_fps = 1 / max(gaps)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        hw = min(w, 520)
        x0 = (w - hw) / 2
        lane_w = hw / 5

        p.fillRect(QRectF(x0, 0, hw, h), QColor(10, 10, 20, 150))
        p.setPen(QPen(QColor(255, 255, 255, 60), 2))
        for i in range(1, 5):
            p.drawLine(int(x0 + i * lane_w), 0, int(x0 + i * lane_w), h)

        strike_y = h - 120
        for i, color in enumerate(LANE_COLORS):
            c = QColor(color)
            p.setPen(QPen(c, 4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(x0 + i * lane_w + lane_w * 0.15, strike_y - lane_w * 0.35, lane_w * 0.7, lane_w * 0.7))

        # Notas de prueba: la posición sale del reloj, no del número de frame,
        # así que si se pierde un frame la nota salta pero no se desincroniza.
        p.setPen(Qt.PenStyle.NoPen)
        spacing = 0.5
        for lane, color in enumerate(LANE_COLORS):
            p.setBrush(QColor(color))
            phase = (now + lane * 0.13) % spacing
            for k in range(int(NOTE_TRAVEL_S / spacing) + 2):
                time_to_hit = k * spacing - phase
                y = strike_y - time_to_hit / NOTE_TRAVEL_S * strike_y
                if -30 < y < h + 30:
                    p.drawRoundedRect(QRectF(x0 + lane * lane_w + lane_w * 0.15, y - 12, lane_w * 0.7, 24), 8, 8)

        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        p.drawText(int(x0 + 12), 30, f"{self.fps:5.1f} fps  (mín {self.min_fps:5.1f})  monitor {self.refresh_hz:.0f} Hz")
        p.end()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hotkey", default="ctrl+alt+g", help="atajo para mostrar/ocultar (ej: f9, ctrl+alt+g)")
    parser.add_argument("--fullscreen", action="store_true", help="ventana del tamaño de la pantalla (peor caso)")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    # Resolución del temporizador de Windows a 1 ms; sin esto los timers van a ~15,6 ms.
    winmm.timeBeginPeriod(1)

    app = QApplication(sys.argv)
    overlay = Overlay(args.fullscreen)

    hotkeys = HotkeyThread({HOTKEY_TOGGLE: parse_hotkey(args.hotkey), HOTKEY_QUIT: parse_hotkey("ctrl+alt+q")})
    # La señal se emite desde el hilo Win32; en cola para que el slot corra en el hilo de Qt.
    hotkeys.pressed.connect(overlay.on_hotkey, Qt.ConnectionType.QueuedConnection)
    hotkeys.start()
    for err in hotkeys.errors:
        print("AVISO:", err)

    # Ctrl+C en la consola: Qt no deja a Python atender señales si no le damos tiempo.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()
    tick.start(200)
    tick.timeout.connect(lambda: None)

    last = [time.process_time(), time.perf_counter()]

    def report() -> None:
        cpu, wall = time.process_time(), time.perf_counter()
        pct = 100 * (cpu - last[0]) / (wall - last[1])
        last[:] = [cpu, wall]
        if overlay.isVisible():
            print(f"{overlay.fps:5.1f} fps (mín {overlay.min_fps:5.1f})  CPU {pct:4.1f}%")

    timer = QTimer()
    timer.timeout.connect(report)
    timer.start(5000)

    overlay.show()
    print(f"Overlay en marcha. {args.hotkey} muestra/oculta, ctrl+alt+q sale.")
    t0 = time.perf_counter()
    code = app.exec()
    hotkeys.stop()
    winmm.timeEndPeriod(1)
    print(f"Fin tras {time.perf_counter() - t0:.0f} s")
    return code


if __name__ == "__main__":
    sys.exit(main())
