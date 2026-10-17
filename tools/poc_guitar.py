"""Fase 0 - Guitarra: lista los mandos SDL e imprime botones, strum y palanca.

Uso:
    uv run --project app python tools/poc_guitar.py            # sin ventana SDL
    uv run --project app python tools/poc_guitar.py --window   # con ventana, para probar la pérdida de foco

Prueba del foco: con el script corriendo, haz clic en otra aplicación (el
navegador, el explorador...) y sigue tocando. Si los eventos siguen saliendo,
el mando se lee en segundo plano. En la app real la ventana será de Qt, no de
SDL, así que el caso importante es el modo por defecto (sin --window).

Guitarras de PS3 con dongle USB: los trastes suelen ser botones, el strum es
el hat (cruceta) arriba/abajo y la palanca (whammy) un eje.
"""

import argparse
import os
import sys
import time

# Tiene que ir antes de importar pygame: sin esto SDL deja de entregar
# eventos del mando cuando su ventana pierde el foco.
os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"
# Wiimote por Bluetooth leído directamente por SDL (driver HIDAPI). Si la
# guitarra no aparece así, la alternativa es WiitarThing, que la convierte en
# un mando de Xbox 360 virtual.
os.environ["SDL_JOYSTICK_HIDAPI_WII"] = "1"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame  # noqa: E402

AXIS_DEADZONE = 0.08


def describe(joy: pygame.joystick.JoystickType) -> str:
    return (
        f"[{joy.get_instance_id()}] {joy.get_name()!r}  guid={joy.get_guid()}  "
        f"botones={joy.get_numbuttons()} ejes={joy.get_numaxes()} "
        f"hats={joy.get_numhats()} power={joy.get_power_level()}"
    )


def foreground_window_title() -> str:
    """Título de la ventana con foco, para confirmar que no somos nosotros."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        return buf.value or "<sin título>"
    except Exception:
        return "?"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--window", action="store_true", help="abre una ventana SDL pequeña")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    pygame.init()
    if args.window:
        pygame.display.set_mode((320, 120))
        pygame.display.set_caption("poc_guitar - haz clic fuera de esta ventana")
    else:
        # El sistema de eventos de pygame necesita el subsistema de vídeo,
        # pero no hace falta crear ninguna ventana.
        pygame.display.init()
    pygame.joystick.init()

    print(f"pygame-ce {pygame.version.ver}, SDL {'.'.join(map(str, pygame.get_sdl_version()))}")
    print(f"Mandos detectados: {pygame.joystick.get_count()}")
    joysticks: dict[int, pygame.joystick.JoystickType] = {}
    for i in range(pygame.joystick.get_count()):
        joy = pygame.joystick.Joystick(i)
        joysticks[joy.get_instance_id()] = joy
        print("  " + describe(joy))
    print("Toca la guitarra. Ctrl+C para salir.\n")

    last_axis: dict[tuple[int, int], float] = {}
    last_focus = ""
    t0 = time.perf_counter()
    clock = pygame.time.Clock()
    try:
        while True:
            for ev in pygame.event.get():
                ms = int((time.perf_counter() - t0) * 1000)
                focus = foreground_window_title()
                tag = f"{ms:>8} ms"
                if focus != last_focus:
                    print(f"{tag}  -- foco en: {focus}")
                    last_focus = focus

                if ev.type == pygame.JOYDEVICEADDED:
                    joy = pygame.joystick.Joystick(ev.device_index)
                    joysticks[joy.get_instance_id()] = joy
                    print(f"{tag}  CONECTADO {describe(joy)}")
                elif ev.type == pygame.JOYDEVICEREMOVED:
                    joysticks.pop(ev.instance_id, None)
                    print(f"{tag}  DESCONECTADO id={ev.instance_id}")
                elif ev.type == pygame.JOYBUTTONDOWN:
                    print(f"{tag}  joy{ev.instance_id} botón {ev.button:>2} PULSADO")
                elif ev.type == pygame.JOYBUTTONUP:
                    print(f"{tag}  joy{ev.instance_id} botón {ev.button:>2} suelto")
                elif ev.type == pygame.JOYHATMOTION:
                    print(f"{tag}  joy{ev.instance_id} hat {ev.hat} = {ev.value}   (strum en PS3: (0,1)/(0,-1))")
                elif ev.type == pygame.JOYAXISMOTION:
                    key = (ev.instance_id, ev.axis)
                    if abs(ev.value - last_axis.get(key, 0.0)) >= AXIS_DEADZONE:
                        last_axis[key] = ev.value
                        print(f"{tag}  joy{ev.instance_id} eje {ev.axis} = {ev.value:+.2f}")
                elif ev.type == pygame.QUIT:
                    return 0
            clock.tick(500)
    except KeyboardInterrupt:
        return 0
    finally:
        pygame.quit()


if __name__ == "__main__":
    sys.exit(main())
