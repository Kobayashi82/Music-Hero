"""Grabadora de ritmo: marca con una tecla el ritmo que sientes mientras suena la canción en AIMP.

Uso:
    uv run --project app tap

    Pon una canción en AIMP y tamborilea con Espacio:
        pulsar           "ta"   (nota corta)
        mantener         "taaaa" (nota larga)
    Para rehacer un trozo, retrocede en AIMP y vuelve a marcarlo: sustituye lo anterior.
    Al cambiar de canción se guarda y se empieza a grabar la nueva.
    Ctrl+Alt+Q termina (también Ctrl+C).

Espacio solo se reserva mientras AIMP está sonando: si pausas, el teclado
vuelve a la normalidad. El ritmo se guarda en data/taps/<canción>.json y el
generador lo usa automáticamente (generate canción.mp3).
"""

import ctypes
import hashlib
import json
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

from .aimp import Aimp, PositionClock, Track

ROOT = Path(__file__).resolve().parents[3]
TAPS_DIR = Path(os.environ.get("MUSIC_HERO_TAPS_DIR", ROOT / "data" / "taps"))  # la prueba automática usa otra
FORMAT_VERSION = 1

user32 = ctypes.windll.user32
winmm = ctypes.windll.winmm
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
WM_HOTKEY, PM_REMOVE = 0x0312, 0x1
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
VK_SPACE = 0x20
ID_TAP, ID_QUIT = 1, 2
LONG_MS = 250  # a partir de aquí se muestra como "taaaa" (el generador decide con el tempo)


def taps_path(audio_file: str) -> Path:
    return TAPS_DIR / f"{Path(audio_file).stem}.json"


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fmt(ms: int) -> str:
    return f"{ms // 60000}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def _merge_ranges(ranges: list[list[int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


class Session:
    """Grabación de una canción. Al guardar, lo grabado sustituye a lo anterior en los tramos escuchados."""

    def __init__(self, track: Track):
        self.track = track
        self.taps: list[list[int]] = []  # [inicio, fin] en ms
        self.covered: list[list[int]] = []  # tramos escuchados en esta sesión
        self.segment_start: int | None = None
        self.segment_end: int | None = None
        self.dirty = False

    def listening(self, pos: int) -> None:
        if self.segment_start is None:
            self.segment_start = pos
        self.segment_end = max(self.segment_end or pos, pos)

    def close_segment(self) -> None:
        if self.segment_start is not None and self.segment_end is not None and self.segment_end > self.segment_start:
            self.covered.append([self.segment_start, self.segment_end])
            self.dirty = True
        self.segment_start = self.segment_end = None

    def seek(self, pos: int) -> int:
        """Salto: cierra el tramo y descarta lo marcado desde ahí (se va a volver a marcar)."""
        self.close_segment()
        before = len(self.taps)
        self.taps = [t for t in self.taps if t[0] < pos]
        self.dirty = self.dirty or before != len(self.taps)
        return before - len(self.taps)

    def add(self, start: int, end: int) -> None:
        self.taps.append([start, max(end, start + 1)])
        self.dirty = True

    def save(self) -> Path | None:
        self.close_segment()
        if not self.dirty:
            return None
        path = taps_path(self.track.file)
        old_taps: list[list[int]] = []
        old_covered: list[list[int]] = []
        sha = None
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            old_taps, old_covered, sha = old.get("taps", []), old.get("covered", []), old.get("audio_sha256")
        covered = _merge_ranges(self.covered)
        keep = [t for t in old_taps if not any(a <= t[0] <= b for a, b in covered)]
        data = {
            "version": FORMAT_VERSION,
            "audio_file": self.track.file,
            "audio_sha256": sha or sha256_file(self.track.file),
            "title": self.track.title,
            "artist": self.track.artist,
            "duration_ms": self.track.duration_ms,
            "covered": _merge_ranges(old_covered + covered),
            "taps": sorted(keep + self.taps),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
        self.covered = covered
        self.dirty = False
        return path


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        return 0
    aimp = Aimp()
    if not aimp.connected():
        print("AIMP no está abierto.")
        return 1
    clock = PositionClock(aimp)
    if not user32.RegisterHotKey(None, ID_QUIT, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("Q")):
        print("AVISO: no se pudo registrar Ctrl+Alt+Q; usa Ctrl+C para terminar.")
    print("Grabadora de ritmo. Espacio = ta (mantén para taaaa). Ctrl+Alt+Q termina.")

    winmm.timeBeginPeriod(1)
    session: Session | None = None
    space_registered = False
    pressed_at: float | None = None
    last_save = time.perf_counter()
    msg = wintypes.MSG()
    try:
        while True:
            if not aimp.connected():
                print("AIMP se ha cerrado.")
                break
            clock.update()

            track = aimp.track()
            if track and (session is None or track.file != session.track.file):
                if session:
                    saved = session.save()
                    if saved:
                        print(f"   guardado: {saved.name} ({len(json.loads(saved.read_text(encoding='utf-8'))['taps'])} toques)")
                session = Session(track)
                prev = taps_path(track.file)
                extra = f" (ya hay {len(json.loads(prev.read_text(encoding='utf-8'))['taps'])} toques guardados)" if prev.exists() else ""
                print(f"\n== {track.artist} - {track.title}{extra}")

            if clock.seeked_to is not None and session:
                dropped = session.seek(clock.seeked_to)
                print(f"   salto a {fmt(clock.seeked_to)}" + (f": se descartan {dropped} toques para volver a marcarlos" if dropped else ""))
                clock.seeked_to = None

            playing = clock.playing
            if session and playing:
                session.listening(clock.estimate())
            elif session:
                session.close_segment()

            # Espacio reservado solo mientras suena.
            if playing and not space_registered:
                space_registered = bool(user32.RegisterHotKey(None, ID_TAP, MOD_NOREPEAT, VK_SPACE))
                if not space_registered:
                    print("AVISO: Espacio lo usa otra aplicación")
            elif not playing and space_registered:
                user32.UnregisterHotKey(None, ID_TAP)
                space_registered = False
                pressed_at = None

            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message != WM_HOTKEY:
                    continue
                if msg.wParam == ID_QUIT:
                    raise KeyboardInterrupt
                if msg.wParam == ID_TAP and session and playing and pressed_at is None:
                    pressed_at = time.perf_counter()

            if pressed_at is not None and not user32.GetAsyncKeyState(VK_SPACE) & 0x8000:
                released = time.perf_counter()
                start, end = clock.estimate(pressed_at), clock.estimate(released)
                session.add(start, end)
                kind = f"taaaa ({end - start} ms)" if end - start >= LONG_MS else "ta"
                print(f"   {fmt(start)}  {kind}")
                pressed_at = None

            if session and time.perf_counter() - last_save > 10:
                session.save()
                last_save = time.perf_counter()
            time.sleep(0.001)
    except KeyboardInterrupt:
        pass
    finally:
        if space_registered:
            user32.UnregisterHotKey(None, ID_TAP)
        user32.UnregisterHotKey(None, ID_QUIT)
        winmm.timeEndPeriod(1)
        if session:
            saved = session.save()
            if saved:
                print(f"   guardado: {saved}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
