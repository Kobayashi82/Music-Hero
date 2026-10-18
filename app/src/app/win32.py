"""Win32 para el overlay y el teclado (técnicas del Lander, probadas en la fase 0: tools/poc_overlay.py)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
winmm = ctypes.windll.winmm

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP = 0x8000
PM_REMOVE = 0x1
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x20, 0x80, 0x8000000
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_NOOWNERZORDER = 0x1, 0x2, 0x10, 0x200

VK = {"up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "enter": 0x0D, "space": 0x20, "esc": 0x1B,
      "backspace": 0x08, "tab": 0x09, "pause": 0x13, "scrolllock": 0x91, "insert": 0x2D, "home": 0x24,
      "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "delete": 0x2E, "capslock": 0x14,
      "media_play": 0xB3, "media_next": 0xB0, "media_prev": 0xB1, "media_stop": 0xB2, "mute": 0xAD,
      "volume_down": 0xAE, "volume_up": 0xAF}
VK |= {f"num{i}": 0x60 + i for i in range(10)}
VK_NAMES = {v: k for k, v in VK.items()}
# para enseñar las teclas en los menús
LABELS = {"up": "Flecha arriba", "down": "Flecha abajo", "left": "Flecha izquierda", "right": "Flecha derecha",
          "enter": "Intro", "space": "Espacio", "esc": "Esc", "backspace": "Retroceso", "tab": "Tab",
          "pause": "Pausa", "scrolllock": "Bloq Despl", "insert": "Insert", "home": "Inicio", "end": "Fin",
          "pageup": "Re Pág", "pagedown": "Av Pág", "delete": "Supr", "capslock": "Bloq Mayús",
          "media_play": "Play/Pausa", "media_next": "Pista siguiente", "media_prev": "Pista anterior",
          "media_stop": "Stop", "mute": "Silencio", "volume_down": "Bajar volumen", "volume_up": "Subir volumen",
          "ctrl": "Ctrl", "alt": "Alt", "shift": "Mayús", "win": "Win"}
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
MODIFIER_VKS = {0x10: "shift", 0xA0: "shift", 0xA1: "shift", 0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
                0x12: "alt", 0xA4: "alt", 0xA5: "alt", 0x5B: "win", 0x5C: "win"}
WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105

user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_uint]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.VkKeyScanW.restype = ctypes.c_short
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]


def vk_of(key: str) -> int:
    key = key.lower()
    if key in VK:
        return VK[key]
    if len(key) == 1 and key.isascii() and key.isalnum():
        return ord(key.upper())
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return 0x70 + int(key[1:]) - 1
    if key.startswith("vk_"):  # teclas sin nombre propio (ñ, signos...): su código
        return int(key[3:], 16)
    raise ValueError(f"tecla no reconocida: {key!r}")


def key_of(vk: int) -> str:
    """Nombre guardable de una tecla virtual (lo contrario de vk_of)."""
    if vk in VK_NAMES:
        return VK_NAMES[vk]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk).lower()
    if 0x70 <= vk <= 0x87:
        return f"f{vk - 0x70 + 1}"
    return f"vk_{vk:02x}"


def combo_label(combo: str) -> str:
    """'ctrl+alt+h' -> 'Ctrl+Alt+H'; las teclas sin nombre, como las llama Windows con la distribución actual."""
    out = []
    for part in combo.lower().split("+"):
        if part in LABELS:
            out.append(LABELS[part])
        elif part.startswith("vk_"):
            scan = user32.MapVirtualKeyW(int(part[3:], 16), 0)
            buf = ctypes.create_unicode_buffer(32)
            n = user32.GetKeyNameTextW(scan << 16, buf, 32) if scan else 0
            out.append(buf.value[:n] if n else part)
        elif part.startswith("num") and part[3:].isdigit():
            out.append(f"Num {part[3:]}")
        else:
            out.append(part.upper())
    return "+".join(out)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
user32.GetKeyNameTextW.argtypes = [wintypes.LONG, wintypes.LPWSTR, ctypes.c_int]
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT


class KeyCatcher:
    """Atrapa la próxima tecla (con Ctrl/Alt/Mayús/Win si with_mods) con un gancho de teclado de bajo nivel:
    mientras está puesto, ninguna tecla llega a ninguna aplicación. Necesita que el hilo que lo pone atienda
    sus mensajes (PeekMessage). done(combo) recibe 'ctrl+alt+h', o '' si se pulsa Esc (cancelar)."""

    def __init__(self, with_mods: bool, done):
        self.with_mods, self.done = with_mods, done
        self.mods: set[str] = set()
        self._proc = HOOKPROC(self._hook)  # hay que guardarla: si se libera, Windows llama a basura
        self.hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0)

    def _hook(self, code: int, wparam: int, lparam: int) -> int:
        if code < 0 or not self.hook:
            return user32.CallNextHookEx(None, code, wparam, lparam)
        vk = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents.vkCode
        mod = MODIFIER_VKS.get(vk)
        if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            if mod:
                self.mods.add(mod)
            else:
                combo = "" if vk == VK["esc"] else key_of(vk)
                if combo and self.with_mods:
                    combo = "+".join([m for m in ("ctrl", "alt", "shift", "win") if m in self.mods] + [combo])
                self.close()
                self.done(combo)
        elif wparam in (WM_KEYUP, WM_SYSKEYUP) and mod:
            self.mods.discard(mod)
        return 1  # se la queda: no llega a nadie

    def close(self) -> None:
        if self.hook:
            user32.UnhookWindowsHookEx(self.hook)
            self.hook = None


def vk_of_char(c: str) -> int | None:
    """Tecla virtual que escribe c sin modificadores con la distribución actual (la ñ incluida); None si no hay."""
    r = user32.VkKeyScanW(c)
    return r & 0xFF if r != -1 and not r >> 8 & 0xFF else None


def parse_hotkey(text: str) -> tuple[int, int]:
    """'ctrl+alt+h' -> (modificadores | MOD_NOREPEAT, tecla virtual)."""
    mods, vk = 0, None
    for part in text.lower().replace(" ", "").split("+"):
        if part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "alt":
            mods |= MOD_ALT
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part == "win":
            mods |= MOD_WIN
        else:
            vk = vk_of(part)
    if vk is None:
        raise ValueError(f"falta la tecla en {text!r}")
    return mods | MOD_NOREPEAT, vk


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def bring_to_top(hwnd: int) -> None:
    """Recupera el primer puesto entre las ventanas «siempre encima» (subtítulos, notificaciones...)."""
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)


def make_click_through(hwnd: int) -> bool:
    wanted = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    if style & wanted != wanted:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | wanted)
    return user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & wanted == wanted


def set_click_through(hwnd: int, on: bool) -> None:
    """Deja pasar los clics (on) o los recibe (off, con un menú abierto). El resto del estilo no cambia: sigue
    sin quitar el foco a nadie al pulsar."""
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    new = style | WS_EX_TRANSPARENT if on else style & ~WS_EX_TRANSPARENT
    if new != style:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new)
