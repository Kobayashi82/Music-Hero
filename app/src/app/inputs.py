"""Entrada del juego sin foco: guitarra de Wii (HID) y teclado (RegisterHotKey, como el Lander).

Cada fuente corre en su hilo y deja eventos con su instante de time.perf_counter() en una cola; el
juego los pasa a ms de la canción con el reloj del reproductor (Player.position_ms(at)).

Teclado, con el juego activo (las teclas no llegan a la app que tenga el foco):
    A S D F G          trastes verde, rojo, amarillo, azul, naranja
    flechas arriba/abajo, Intro   strum (en los menús: mover; Intro elige)
    Espacio            menú (pausa)   Retroceso   reiniciar la canción (en los menús: volver)
    Tab                cambiar de dificultad sin parar la canción
En el buscador, letras, números y Espacio escriben (los trastes siguen en la guitarra).
Siempre: Ctrl+Alt+H mostrar/ocultar (oculto = pausa y teclado libre), Ctrl+Alt+Q salir.
Guitarra: + menú (pausa), − cambiar de dificultad; en los menús, strum mover, verde o + elegir,
rojo o − volver. Si la guitarra se apaga o se enciende más tarde, se reconecta sola.
"""

from __future__ import annotations

import ctypes
import queue
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

from . import win32

FRET_KEYS = ("a", "s", "d", "f", "g")
STRUM_KEYS = ("up", "down")
CONTROL_KEYS = {"space": "pause", "backspace": "restart", "tab": "difficulty", "enter": "enter"}
TEXT_CHARS = "abcdefghijklmnñopqrstuvwxyz0123456789 "
GLOBAL_HOTKEYS = {"toggle": "ctrl+alt+h", "quit": "ctrl+alt+q"}


@dataclass
class InputEvent:
    t: float  # time.perf_counter()
    kind: str  # "fret" | "strum" | "control" | "char"
    value: int | str = 0  # traste 0..4, dirección del strum (-1 arriba, 1 abajo), nombre del control o letra
    down: bool = True  # False: se suelta (trastes y strum; mantener el strum desplaza los menús)


class Inputs:
    def __init__(self, hotkeys: dict[str, str] | None = None):
        self.events: queue.SimpleQueue[InputEvent] = queue.SimpleQueue()
        self.keyboard = KeyboardSource(self.events, {**GLOBAL_HOTKEYS, **(hotkeys or {})})
        self.guitar = GuitarSource(self.events)
        self.errors: list[str] = []

    def start(self) -> None:
        self.keyboard.start()
        self.errors += self.keyboard.errors
        self.guitar.start()  # su estado lo enseña el juego (guitar.connected)

    def stop(self) -> None:
        self.keyboard.stop()
        self.guitar.stop()

    def set_game_keys(self, enabled: bool) -> None:
        self.keyboard.set_game_keys(enabled)

    def set_text_mode(self, enabled: bool) -> None:
        self.keyboard.set_text_mode(enabled)

    def drain(self) -> list[InputEvent]:
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out


class KeyboardSource:
    """Atajos globales en un hilo con su bucle de mensajes; las sueltas se leen con GetAsyncKeyState."""

    _SET_GAME_KEYS = win32.WM_APP + 1
    _SET_TEXT_MODE = win32.WM_APP + 2

    def __init__(self, events: queue.SimpleQueue, hotkeys: dict[str, str]):
        self.events = events
        self.hotkeys = hotkeys
        self.errors: list[str] = []
        self._ids: dict[int, tuple[str, int | str, int]] = {}  # id -> (tipo, valor, tecla virtual)
        self._thread_id = 0
        self._game = False
        self._text = False
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="teclado")

    def start(self) -> None:
        self._thread.start()
        self._ready.wait()

    def stop(self) -> None:
        if self._thread_id:
            win32.user32.PostThreadMessageW(self._thread_id, win32.WM_QUIT, 0, 0)
            self._thread.join(timeout=1)

    def set_game_keys(self, enabled: bool) -> None:
        win32.user32.PostThreadMessageW(self._thread_id, self._SET_GAME_KEYS, int(enabled), 0)

    def set_text_mode(self, enabled: bool) -> None:
        """Buscador: las letras (A S D F G incluidas) y Espacio escriben en vez de tocar o pausar."""
        win32.user32.PostThreadMessageW(self._thread_id, self._SET_TEXT_MODE, int(enabled), 0)

    def _sync_keys(self) -> None:
        """Registra las teclas del juego (y las de escribir en modo texto) según el estado."""
        for hk_id in [i for i in self._ids if i >= 100]:
            win32.user32.UnregisterHotKey(None, hk_id)
            del self._ids[hk_id]
        if not self._game:
            return
        keys = {110 + i: ("strum", -1 if k == "up" else 1, win32.vk_of(k)) for i, k in enumerate(STRUM_KEYS)}
        keys |= {120 + i: ("control", name, win32.vk_of(k)) for i, (k, name) in enumerate(CONTROL_KEYS.items())
                 if not (self._text and k == "space")}
        if self._text:
            keys |= {200 + i: ("char", c, vk) for i, c in enumerate(TEXT_CHARS) if (vk := win32.vk_of_char(c))}
        else:
            keys |= {100 + i: ("fret", i, win32.vk_of(k)) for i, k in enumerate(FRET_KEYS)}
        for hk_id, (kind, value, vk) in keys.items():
            if win32.user32.RegisterHotKey(None, hk_id, win32.MOD_NOREPEAT, vk):
                self._ids[hk_id] = (kind, value, vk)
            elif kind != "char":
                self.errors.append(f"la tecla {value!r} ya la usa otra aplicación")

    def _run(self) -> None:
        self._thread_id = win32.kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        win32.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # crea la cola de mensajes del hilo
        for i, (name, combo) in enumerate(self.hotkeys.items()):
            mods, vk = win32.parse_hotkey(combo)
            if win32.user32.RegisterHotKey(None, 1 + i, mods, vk):
                self._ids[1 + i] = ("control", name, vk)
            else:
                self.errors.append(f"no se pudo registrar {combo} (¿lo usa otra app?)")
        self._ready.set()
        win32.winmm.timeBeginPeriod(1)
        held: dict[int, tuple[str, int]] = {}  # tecla virtual -> (traste o strum, valor), para ver la suelta
        try:
            while True:
                while win32.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, win32.PM_REMOVE):
                    now = time.perf_counter()
                    if msg.message == win32.WM_QUIT:
                        return
                    if msg.message in (self._SET_GAME_KEYS, self._SET_TEXT_MODE):
                        if msg.message == self._SET_GAME_KEYS:
                            self._game = bool(msg.wParam)
                        else:
                            self._text = bool(msg.wParam)
                        for kind, value in held.values():  # lo pulsado se suelta: no se queda pegado
                            self.events.put(InputEvent(now, kind, value, False))
                        held.clear()
                        self._sync_keys()
                    elif msg.message == win32.WM_HOTKEY and msg.wParam in self._ids:
                        kind, value, vk = self._ids[msg.wParam]
                        self.events.put(InputEvent(now, kind, value, True))
                        if kind in ("fret", "strum"):
                            held[vk] = (kind, value)
                now = time.perf_counter()
                for vk in [vk for vk in held if not win32.key_down(vk)]:
                    self.events.put(InputEvent(now, *held.pop(vk), False))
                time.sleep(0.001)
        finally:
            for hk_id in list(self._ids):
                win32.user32.UnregisterHotKey(None, hk_id)
            win32.winmm.timeEndPeriod(1)


class GuitarSource:
    """Guitarra de Wii por HID (wii_guitar.py). Si no está o se desconecta, lo reintenta cada pocos segundos."""

    RETRY_S = 2.0

    def __init__(self, events: queue.SimpleQueue):
        self.events = events
        self.error = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._guitar = None
        self.connected = False

    def start(self) -> bool:
        """Lanza el hilo; True si la guitarra estaba ya al empezar."""
        found = self._open() is not None
        self._thread = threading.Thread(target=self._run, daemon=True, name="guitarra")
        self._thread.start()
        return found

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)

    def _open(self):
        try:
            from .wii_guitar import WiiGuitar

            self._guitar = WiiGuitar.open()
        except Exception as e:  # noqa: BLE001 - sin guitarra se juega con teclado
            self.error = str(e)
            self._guitar = None
        self.connected = self._guitar is not None
        return self._guitar

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._guitar is None and (self._stop.wait(self.RETRY_S) or self._open() is None):
                continue
            try:
                self._read(self._guitar)
            except Exception as e:  # noqa: BLE001 - Wiimote desconectado o apagado
                self.error = str(e)
            finally:
                self.connected = False
                self._guitar.close()
                self._guitar = None

    def _read(self, guitar) -> None:
        prev = None
        while not self._stop.is_set():
            s = guitar.poll(20)
            if s is None:
                continue
            now = time.perf_counter()
            if prev is not None:
                for i, (a, b) in enumerate(zip(prev.frets, s.frets)):
                    if a != b:
                        self.events.put(InputEvent(now, "fret", i, b))
                if s.strum_up != prev.strum_up:
                    self.events.put(InputEvent(now, "strum", -1, s.strum_up))
                if s.strum_down != prev.strum_down:
                    self.events.put(InputEvent(now, "strum", 1, s.strum_down))
                if s.start and not prev.start:
                    self.events.put(InputEvent(now, "control", "start"))
                if s.select and not prev.select:
                    self.events.put(InputEvent(now, "control", "select"))
            prev = s
