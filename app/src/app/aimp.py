"""AIMP por su API remota (ventana "AIMP2_RemoteInfo"): canción, archivo, estado y posición.

AIMP no publica en SMTC. Su posición se actualiza cada ~32 ms en pasos de 30 ms;
PositionClock la interpola con el reloj del sistema para tener precisión de ms.
"""

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass

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
WM_AIMP_COMMAND = 0x0400 + 0x75
WM_AIMP_PROPERTY = 0x0400 + 0x77
PROP_GET, PROP_SET = 0, 1
PROP_VERSION, PROP_POSITION, PROP_DURATION, PROP_STATE = 0x10, 0x20, 0x30, 0x40
CMD_PLAY, CMD_PAUSE, CMD_NEXT, CMD_PREV = 13, 15, 17, 18
STOPPED, PAUSED, PLAYING = 0, 1, 2
FILE_MAP_READ = 0x0004


class _RemoteFileInfo(ctypes.Structure):
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


@dataclass
class Track:
    file: str
    title: str
    artist: str
    album: str
    duration_ms: int


class Aimp:
    """Conexión a AIMP. Todas las llamadas devuelven None/0 si AIMP no está abierto."""

    def __init__(self) -> None:
        self.hwnd = 0

    def connected(self) -> bool:
        self.hwnd = user32.FindWindowW(REMOTE_CLASS, None) or 0
        return bool(self.hwnd)

    def _prop(self, prop: int, value: int | None = None) -> int:
        if not self.hwnd:
            return 0
        if value is None:
            return user32.SendMessageW(self.hwnd, WM_AIMP_PROPERTY, prop | PROP_GET, 0)
        return user32.SendMessageW(self.hwnd, WM_AIMP_PROPERTY, prop | PROP_SET, value)

    def position(self) -> int:
        return self._prop(PROP_POSITION)

    def seek(self, ms: int) -> None:
        self._prop(PROP_POSITION, ms)

    def state(self) -> int:
        return self._prop(PROP_STATE)

    def duration(self) -> int:
        return self._prop(PROP_DURATION)

    def command(self, cmd: int) -> None:
        if self.hwnd:
            user32.SendMessageW(self.hwnd, WM_AIMP_COMMAND, cmd, 0)

    def track(self) -> Track | None:
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
        info = _RemoteFileInfo.from_buffer_copy(raw)
        offset = ctypes.sizeof(_RemoteFileInfo)
        fields = {}
        for name in ("Album", "Artist", "Date", "FileName", "Genre", "Title"):
            n = getattr(info, f"{name}Length")
            fields[name] = raw[offset:offset + n * 2].decode("utf-16-le", errors="replace")
            offset += n * 2
        if not fields["FileName"]:
            return None
        return Track(fields["FileName"], fields["Title"], fields["Artist"], fields["Album"], info.Duration)


class PositionClock:
    """Posición de AIMP interpolada con el reloj del sistema.

    AIMP da la posición en pasos de ~30 ms. Cada vez que el valor cambia, el
    valor nuevo es lo más fresco que hay: offset = posición - reloj en ese
    instante. Se toma el mayor offset de los últimos segundos (el cambio con
    menos retraso) y la posición estimada es reloj + offset.
    """

    WINDOW_S = 3.0
    JUMP_MS = 300  # un salto mayor que esto es un seek

    def __init__(self, aimp: Aimp) -> None:
        self.aimp = aimp
        self.changes: list[tuple[float, int]] = []  # (reloj s, posición ms)
        self.last_pos: int | None = None
        self.playing = False
        self.seeked_to: int | None = None  # se rellena al detectar un seek, para quien lo quiera

    @staticmethod
    def now() -> float:
        return time.perf_counter()

    def update(self) -> None:
        """Llamar a menudo (cada pocos ms)."""
        t = self.now()
        pos = self.aimp.position()
        self.playing = self.aimp.state() == PLAYING
        if pos == self.last_pos:
            return
        if self.changes and self.playing:
            expected = self.estimate(t)
            if abs(pos - expected) > self.JUMP_MS:
                self.changes.clear()
                self.seeked_to = pos
        elif self.last_pos is not None and abs(pos - self.last_pos) > self.JUMP_MS + 100:
            self.seeked_to = pos  # seek con la canción en pausa
        self.last_pos = pos
        if self.playing:
            self.changes.append((t, pos))
            while self.changes and t - self.changes[0][0] > self.WINDOW_S:
                self.changes.pop(0)

    def estimate(self, t: float | None = None) -> int:
        t = self.now() if t is None else t
        if not self.playing or not self.changes:
            return self.last_pos or 0
        offset = max(p - c * 1000 for c, p in self.changes)
        return int(round(t * 1000 + offset))
