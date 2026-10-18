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
      "end": 0x23, "pageup": 0x21, "pagedown": 0x22}

user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_uint]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]


def vk_of(key: str) -> int:
    key = key.lower()
    if key in VK:
        return VK[key]
    if len(key) == 1 and key.isalnum():
        return ord(key.upper())
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return 0x70 + int(key[1:]) - 1
    raise ValueError(f"tecla no reconocida: {key!r}")


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
