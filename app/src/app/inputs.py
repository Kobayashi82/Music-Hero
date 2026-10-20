"""Entrada del juego sin foco: guitarra de Wii (HID) y teclado (RegisterHotKey, como el Lander).

Cada fuente corre en su hilo y deja eventos con su instante de time.perf_counter() en una cola; el
juego los pasa a ms de la canción con el reloj del reproductor (Player.position_ms(at)).

Teclado, con el juego activo (las teclas no llegan a la app que tenga el foco). Estas son las de por defecto
(ACTIONS); se cambian en Ajustes → Teclas y se guardan en config.keys:
    A S D F G          trastes verde, rojo, amarillo, azul, naranja
    flechas arriba/abajo, Intro   strum (en los menús: mover; Intro elige)
    Espacio            menú (pausa)   Esc   volver (jugando: la pausa)   Retroceso   reiniciar la canción
    Tab                cambiar de dificultad sin parar la canción
    E                  activar el star power
    flechas izquierda/derecha   retroceder / avanzar 5 s   Re Pág / Av Pág   subir / bajar el volumen
En el buscador, letras, números y Espacio escriben y Retroceso borra (los trastes siguen en la guitarra).
Siempre: Ctrl+Alt+H mostrar/ocultar (oculto = pausa y teclado libre), Ctrl+Alt+Q salir.
Guitarra: + menú (pausa), − cambiar de dificultad, levantar el mástil activa el star power (acelerómetro del
Wiimote, starpower.Tilt); en los menús, strum mover, verde o + elegir,
rojo o − volver. Si la guitarra se apaga o se enciende más tarde, se reconecta sola.
Wiimote (donde va enchufada la guitarra): A mostrar/ocultar, 1 canción siguiente, 2 anterior, Home al azar
(siguiendo a AIMP, siguiente y anterior se las pide a AIMP); cruceta: izquierda/derecha retroceder/avanzar,
arriba/abajo el volumen (siguiendo a AIMP, el de AIMP).
"""

from __future__ import annotations

import ctypes
import queue
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

from . import win32
from .i18n import N_, TrDict, t
from .starpower import Tilt

# (acción, nombre en Ajustes, tecla por defecto, evento que da). Las globales funcionan siempre (también con el
# juego oculto) y admiten Ctrl/Alt/Mayús/Win; las del juego, solo con el juego a la vista y sin modificadores.
ACTIONS = [
    ("toggle", N_("Mostrar / ocultar"), "ctrl+alt+h", ("control", "toggle")),
    ("quit", N_("Salir"), "ctrl+alt+q", ("control", "quit")),
    ("fret0", N_("Traste verde"), "a", ("fret", 0)),
    ("fret1", N_("Traste rojo"), "s", ("fret", 1)),
    ("fret2", N_("Traste amarillo"), "d", ("fret", 2)),
    ("fret3", N_("Traste azul"), "f", ("fret", 3)),
    ("fret4", N_("Traste naranja"), "g", ("fret", 4)),
    ("strum_up", N_("Strum arriba"), "up", ("strum", -1)),
    ("strum_down", N_("Strum abajo"), "down", ("strum", 1)),
    ("pause", N_("Menú (pausa)"), "space", ("control", "pause")),
    ("back", N_("Volver / pausa"), "esc", ("control", "back")),
    ("restart", N_("Reiniciar la canción"), "backspace", ("control", "restart")),
    ("difficulty", N_("Cambiar de dificultad"), "tab", ("control", "difficulty")),
    ("star", N_("Star power"), "e", ("control", "star")),
    ("enter", N_("Elegir"), "enter", ("control", "enter")),
    ("seek_back", N_("Retroceder 5 s"), "left", ("control", "seek_back")),
    ("seek_fwd", N_("Avanzar 5 s"), "right", ("control", "seek_fwd")),
    ("vol_up", N_("Subir el volumen"), "pageup", ("control", "vol_up")),
    ("vol_down", N_("Bajar el volumen"), "pagedown", ("control", "vol_down")),
]
GLOBAL_ACTIONS = ("toggle", "quit")
DEFAULT_KEYS = {a: key for a, _, key, _ in ACTIONS}
ACTION_NAMES = TrDict({a: name for a, name, _, _ in ACTIONS})  # traducidos al leerlos
ACTION_EVENTS = {a: ev for a, _, _, ev in ACTIONS}
TEXT_CHARS = "abcdefghijklmnñopqrstuvwxyz0123456789 "
BACKSPACE = "\b"  # en el buscador, Retroceso llega como InputEvent("char", BACKSPACE)
# botones del propio Wiimote (los 2 bytes de botones de sus informes, wiibrew.org/wiki/Wiimote) -> control
WIIMOTE_BUTTONS = {0x0008: "toggle", 0x0002: "next", 0x0001: "prev", 0x0080: "random",  # A, 1, 2, Home
                   0x0100: "seek_back", 0x0200: "seek_fwd", 0x0800: "vol_up", 0x0400: "vol_down"}  # cruceta


def keymap(custom: dict[str, str] | None) -> dict[str, str]:
    """Las teclas por defecto con las cambiadas encima (las acciones desconocidas se ignoran)."""
    return DEFAULT_KEYS | {a: k for a, k in (custom or {}).items() if a in DEFAULT_KEYS}


def assign(custom: dict[str, str] | None, action: str, combo: str) -> dict[str, str]:
    """Pone combo a action; si otra acción la tenía, se intercambian. Devuelve solo lo que difiere de lo de
    por defecto (lo que se guarda en la config)."""
    full = keymap(custom)
    other = next((a for a, k in full.items() if k == combo and a != action), None)
    if other:
        full[other] = full[action]
    full[action] = combo
    return {a: k for a, k in full.items() if k != DEFAULT_KEYS[a]}


@dataclass
class InputEvent:
    t: float  # time.perf_counter()
    kind: str  # "fret" | "strum" | "control" | "char" | "captured" (tecla atrapada para Ajustes) | "error"
    value: int | str = 0  # traste 0..4, dirección del strum (-1 arriba, 1 abajo), nombre del control, letra...
    down: bool = True  # False: se suelta (trastes y strum; mantener el strum desplaza los menús)


class Inputs:
    def __init__(self, keys: dict[str, str] | None = None):
        """keys: las teclas cambiadas en Ajustes (config.keys); el resto, las de por defecto."""
        self.events: queue.SimpleQueue[InputEvent] = queue.SimpleQueue()
        self.keyboard = KeyboardSource(self.events, keymap(keys))
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

    def set_keys(self, custom: dict[str, str]) -> None:
        self.keyboard.set_keys(keymap(custom))

    def capture_key(self, with_mods: bool) -> None:
        """La próxima tecla llega como InputEvent("captured", "ctrl+alt+h") ("" si Esc) y no la recibe nadie más."""
        self.keyboard.capture(with_mods)

    def cancel_capture(self) -> None:
        self.keyboard.capture(None)

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
    _SET_KEYS = win32.WM_APP + 3
    _CAPTURE = win32.WM_APP + 4  # wParam: 0 sin modificadores, 1 con ellos, 2 cancelar

    def __init__(self, events: queue.SimpleQueue, keys: dict[str, str]):
        self.events = events
        self.keys = keys  # acción -> tecla ("ctrl+alt+h", "a"...)
        self.errors: list[str] = []
        self._ids: dict[int, tuple[str, int | str, int]] = {}  # id -> (tipo, valor, tecla virtual)
        self._new_keys: dict[str, str] | None = None
        self._catcher: win32.KeyCatcher | None = None
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
        """Buscador: las letras (y números y Espacio) escriben en vez de tocar o pausar."""
        win32.user32.PostThreadMessageW(self._thread_id, self._SET_TEXT_MODE, int(enabled), 0)

    def set_keys(self, keys: dict[str, str]) -> None:
        self._new_keys = dict(keys)
        win32.user32.PostThreadMessageW(self._thread_id, self._SET_KEYS, 0, 0)

    def capture(self, with_mods: bool | None) -> None:
        """Atrapar la próxima tecla (None: dejar de esperarla)."""
        win32.user32.PostThreadMessageW(self._thread_id, self._CAPTURE, 2 if with_mods is None else int(with_mods), 0)

    def _report(self, action: str) -> None:
        text = t("No se pudo usar {key} para «{name}»: la usa otra aplicación",
                 key=win32.combo_label(self.keys[action]), name=ACTION_NAMES[action])
        self.errors.append(text)
        self.events.put(InputEvent(time.perf_counter(), "error", text))

    def _register_globals(self) -> None:
        for hk_id in [i for i in self._ids if i < 100]:
            win32.user32.UnregisterHotKey(None, hk_id)
            del self._ids[hk_id]
        for i, action in enumerate(GLOBAL_ACTIONS):
            mods, vk = win32.parse_hotkey(self.keys[action])
            if win32.user32.RegisterHotKey(None, 1 + i, mods, vk):
                self._ids[1 + i] = (*ACTION_EVENTS[action], vk)
            else:
                self._report(action)

    def _sync_keys(self) -> None:
        """Registra las teclas del juego (y las de escribir en modo texto) según el estado."""
        for hk_id in [i for i in self._ids if i >= 100]:
            win32.user32.UnregisterHotKey(None, hk_id)
            del self._ids[hk_id]
        if not self._game:
            return
        text_vks = set()
        if self._text:
            text_vks = {vk for c in TEXT_CHARS if (vk := win32.vk_of_char(c))} | {win32.VK["backspace"]}
        keys = {}
        for i, (action, _, _, (kind, value)) in enumerate(ACTIONS):
            vk = win32.vk_of(self.keys[action].split("+")[-1])
            if action not in GLOBAL_ACTIONS and vk not in text_vks:  # en el buscador, lo que escribe, escribe
                keys[100 + i] = (kind, value, vk, action)
        if self._text:
            keys |= {200 + i: ("char", c, vk, "") for i, c in enumerate(TEXT_CHARS) if (vk := win32.vk_of_char(c))}
            keys[299] = ("char", BACKSPACE, win32.VK["backspace"], "")
        for hk_id, (kind, value, vk, action) in keys.items():
            if win32.user32.RegisterHotKey(None, hk_id, win32.MOD_NOREPEAT, vk):
                self._ids[hk_id] = (kind, value, vk)
            elif kind != "char":
                self._report(action)

    def _captured(self, combo: str) -> None:
        self._catcher = None
        self.events.put(InputEvent(time.perf_counter(), "captured", combo))

    def _run(self) -> None:
        self._thread_id = win32.kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        win32.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # crea la cola de mensajes del hilo
        self._register_globals()
        self._ready.set()
        win32.winmm.timeBeginPeriod(1)
        held: dict[int, tuple[str, int]] = {}  # tecla virtual -> (traste o strum, valor), para ver la suelta
        try:
            while True:
                while win32.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, win32.PM_REMOVE):
                    now = time.perf_counter()
                    if msg.message == win32.WM_QUIT:
                        return
                    if msg.message in (self._SET_GAME_KEYS, self._SET_TEXT_MODE, self._SET_KEYS):
                        if msg.message == self._SET_GAME_KEYS:
                            self._game = bool(msg.wParam)
                        elif msg.message == self._SET_TEXT_MODE:
                            self._text = bool(msg.wParam)
                        elif self._new_keys is not None:
                            self.keys, self._new_keys = self._new_keys, None
                            self._register_globals()
                        for kind, value in held.values():  # lo pulsado se suelta: no se queda pegado
                            self.events.put(InputEvent(now, kind, value, False))
                        held.clear()
                        self._sync_keys()
                    elif msg.message == self._CAPTURE:
                        if self._catcher:
                            self._catcher.close()
                            self._catcher = None
                        if msg.wParam != 2:  # mientras espera, el gancho se queda todas las teclas
                            self._catcher = win32.KeyCatcher(bool(msg.wParam), self._captured)
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
            if self._catcher:
                self._catcher.close()
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

            self._guitar = WiiGuitar.open(accel=True)  # con el acelerómetro: levantar la guitarra
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
        prev, tilt = None, Tilt()
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
                for mask, name in WIIMOTE_BUTTONS.items():
                    if s.wiimote & mask and not prev.wiimote & mask:
                        self.events.put(InputEvent(now, "control", name))
            if tilt.feed(s.accel):
                self.events.put(InputEvent(now, "control", "star"))
            prev = s
