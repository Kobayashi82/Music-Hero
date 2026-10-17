"""Fase 0 - AIMP: canción, archivo, estado y posición vía la API remota de AIMP.

Uso:
    uv run --project app python tools/poc_aimp.py

AIMP no publica en SMTC, pero tiene una API remota (ventana "AIMP2_RemoteInfo")
que da la posición en ms y la ruta del archivo que suena: con eso la chart se
encuentra por el propio archivo, sin buscar por etiquetas. Solo lee, nunca manda
órdenes al reproductor.

Columnas de posición:
    aimp    lo que reporta AIMP
    paso    cuánto avanzó la posición de AIMP desde la lectura anterior
    reloj   cuánto tiempo real pasó desde la lectura anterior

Prueba: pon una canción, pausa, salta adelante/atrás y cambia de canción. Si
paso ≈ reloj mientras suena, la posición es fina y casi no hace falta interpolar.
"""

import argparse
import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
kernel32.OpenFileMappingW.restype = wintypes.HANDLE
kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.MapViewOfFile.restype = ctypes.c_void_p
kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

# apiRemote.h del SDK de AIMP
REMOTE_CLASS = "AIMP2_RemoteInfo"
REMOTE_MAP_SIZE = 2048
WM_AIMP_PROPERTY = 0x0400 + 0x77
PROP_GET = 0
PROP_VERSION, PROP_POSITION, PROP_DURATION, PROP_STATE = 0x10, 0x20, 0x30, 0x40
STATES = {0: "parado", 1: "pausa", 2: "sonando"}
FILE_MAP_READ = 0x0004


class RemoteFileInfo(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("Deprecated1", wintypes.DWORD),
        ("Active", wintypes.BOOL),
        ("BitRate", wintypes.DWORD),
        ("Channels", wintypes.DWORD),
        ("Duration", wintypes.DWORD),
        ("FileSize", ctypes.c_int64),
        ("FileMark", wintypes.DWORD),
        ("SampleRate", wintypes.DWORD),
        ("TrackNumber", wintypes.DWORD),
        ("AlbumLength", wintypes.DWORD),
        ("ArtistLength", wintypes.DWORD),
        ("DateLength", wintypes.DWORD),
        ("FileNameLength", wintypes.DWORD),
        ("GenreLength", wintypes.DWORD),
        ("TitleLength", wintypes.DWORD),
        ("Deprecated2", wintypes.DWORD * 6),
    ]


def get_prop(hwnd: int, prop: int) -> int:
    return user32.SendMessageW(hwnd, WM_AIMP_PROPERTY, prop | PROP_GET, 0)


def read_track() -> dict | None:
    """Lee la memoria compartida de AIMP: cabecera + cadenas UTF-16 seguidas."""
    handle = kernel32.OpenFileMappingW(FILE_MAP_READ, False, REMOTE_CLASS)
    if not handle:
        return None
    view = kernel32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, REMOTE_MAP_SIZE)
    try:
        if not view:
            return None
        raw = ctypes.string_at(view, REMOTE_MAP_SIZE)
    finally:
        if view:
            kernel32.UnmapViewOfFile(view)
        kernel32.CloseHandle(handle)

    info = RemoteFileInfo.from_buffer_copy(raw)
    offset = ctypes.sizeof(RemoteFileInfo)
    fields = {}
    for name in ("Album", "Artist", "Date", "FileName", "Genre", "Title"):
        n = getattr(info, f"{name}Length")
        fields[name] = raw[offset:offset + n * 2].decode("utf-16-le", errors="replace")
        offset += n * 2
    fields["Duration"] = info.Duration
    fields["SampleRate"] = info.SampleRate
    fields["BitRate"] = info.BitRate
    return fields


def fmt_ms(ms: int) -> str:
    return f"{ms // 60000}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interval", type=float, default=0.05, help="segundos entre lecturas")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    hwnd = user32.FindWindowW(REMOTE_CLASS, None)
    if not hwnd:
        print("AIMP no está abierto (no encuentro la ventana AIMP2_RemoteInfo).")
        return 1
    version = get_prop(hwnd, PROP_VERSION)
    print(f"AIMP encontrado, API remota versión {version >> 16}.{version & 0xFFFF}. Ctrl+C para salir.\n")

    last_file = None
    last_pos = last_wall = None
    try:
        while True:
            hwnd = user32.FindWindowW(REMOTE_CLASS, None)
            if not hwnd:
                print("\nAIMP se ha cerrado.")
                return 0
            wall = time.perf_counter()
            pos = get_prop(hwnd, PROP_POSITION)
            state = get_prop(hwnd, PROP_STATE)
            dur = get_prop(hwnd, PROP_DURATION)

            track = read_track()
            if track and track["FileName"] != last_file:
                last_file = track["FileName"]
                print(f"\n== {track['Artist']} - {track['Title']}  [{track['Album']}]")
                print(f"   archivo: {track['FileName']}")
                print(f"   {track['SampleRate']} Hz, {track['BitRate']} kbps, {fmt_ms(track['Duration'])}")
                last_pos = None

            if last_pos is not None:
                step = pos - last_pos
                clock = int((wall - last_wall) * 1000)
                print(f"\r   {STATES.get(state, state):<8} aimp {fmt_ms(pos)} / {fmt_ms(dur)}"
                      f"   paso {step:>5} ms  reloj {clock:>4} ms   ", end="", flush=True)
            last_pos, last_wall = pos, wall
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
