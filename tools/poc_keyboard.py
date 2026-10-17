"""Fase 0 - Teclado: tocar con el teclado sin que el overlay tenga el foco.

Uso:
    uv run --project app python tools/poc_keyboard.py
    uv run --project app python tools/poc_keyboard.py --hotkey f9

Misma técnica que el Lander: con el modo juego activo, las teclas del juego se
registran como atajos globales (RegisterHotKey). Así llegan aquí aunque el foco
esté en otra app y NO llegan a esa app (no escribes por accidente); el resto
del teclado funciona normal. La pulsación llega como WM_HOTKEY; la suelta se
detecta leyendo el estado físico con GetAsyncKeyState.

Teclas por defecto (luego serán configurables):
    A S D F G          trastes verde, rojo, amarillo, azul, naranja
    Flecha arriba/abajo, Intro   strum
    Ctrl+Alt+H         activar / desactivar el modo juego
    Ctrl+Alt+Q         salir

Prueba: activa el modo juego con el foco en el Bloc de notas y toca; no debe
escribirse nada en el Bloc de notas y aquí deben salir pulsaciones y sueltas.
Desactívalo y comprueba que A S D F G vuelven a escribir normal.
"""

import argparse
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from poc_overlay import WM_HOTKEY, parse_hotkey, user32  # noqa: E402

winmm = ctypes.windll.winmm
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
PM_REMOVE = 0x1
MOD_NOREPEAT = 0x4000

ID_TOGGLE, ID_QUIT = 1, 2
VK_UP, VK_DOWN, VK_RETURN = 0x26, 0x28, 0x0D
GAME_KEYS = {
    # id: (tecla virtual, nombre)
    10: (ord("A"), "verde"),
    11: (ord("S"), "rojo"),
    12: (ord("D"), "amarillo"),
    13: (ord("F"), "azul"),
    14: (ord("G"), "naranja"),
    20: (VK_UP, "strum arriba"),
    21: (VK_DOWN, "strum abajo"),
    22: (VK_RETURN, "strum (intro)"),
}


def set_game_keys(enabled: bool) -> None:
    for hk_id, (vk, name) in GAME_KEYS.items():
        if enabled:
            if not user32.RegisterHotKey(None, hk_id, MOD_NOREPEAT, vk):
                print(f"AVISO: la tecla de {name} ya la usa otra aplicación")
        else:
            user32.UnregisterHotKey(None, hk_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hotkey", default="ctrl+alt+h", help="atajo para activar/desactivar el modo juego")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    for hk_id, combo in ((ID_TOGGLE, args.hotkey), (ID_QUIT, "ctrl+alt+q")):
        if not user32.RegisterHotKey(None, hk_id, *parse_hotkey(combo)):
            print(f"AVISO: no se pudo registrar {combo} (¿lo usa otra app?)")
    print(f"{args.hotkey} activa/desactiva el modo juego, ctrl+alt+q sale.")

    winmm.timeBeginPeriod(1)
    active = False
    held: dict[int, int] = {}  # vk -> ms de pulsación
    t0 = time.perf_counter()
    msg = wintypes.MSG()
    try:
        while True:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message != WM_HOTKEY:
                    continue
                now = int((time.perf_counter() - t0) * 1000)
                if msg.wParam == ID_QUIT:
                    return 0
                if msg.wParam == ID_TOGGLE:
                    active = not active
                    set_game_keys(active)
                    held.clear()
                    print(f"{now:>8} ms  modo juego {'ACTIVO' if active else 'desactivado'}")
                elif msg.wParam in GAME_KEYS:
                    vk, name = GAME_KEYS[msg.wParam]
                    held[vk] = now
                    print(f"{now:>8} ms  {name} PULSADO")
            # Sueltas: estado físico de las teclas pulsadas.
            now = int((time.perf_counter() - t0) * 1000)
            for vk in [vk for vk in held if not user32.GetAsyncKeyState(vk) & 0x8000]:
                name = next(n for v, n in GAME_KEYS.values() if v == vk)
                print(f"{now:>8} ms  {name} suelto ({now - held.pop(vk)} ms)")
            time.sleep(0.001)
    except KeyboardInterrupt:
        return 0
    finally:
        set_game_keys(False)
        user32.UnregisterHotKey(None, ID_TOGGLE)
        user32.UnregisterHotKey(None, ID_QUIT)
        winmm.timeEndPeriod(1)


if __name__ == "__main__":
    sys.exit(main())
