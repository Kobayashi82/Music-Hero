"""engine: el generador como proceso aparte, para la app (fase 7).

La app lo arranca y le habla por líneas JSON: órdenes por stdin, avisos por stdout. Todo lo demás que se
imprima (el detalle de cada canción, avisos de las librerías) sale por stderr, que la app guarda en un log.
Si el motor se cae o se queda sin memoria de vídeo, el juego sigue: la app lo vuelve a lanzar.

    uv run --project generator engine --queue cola.json --out out/charts [--model models/best.pt] [--device auto]

Órdenes (stdin):
    {"cmd": "add", "files": [...], "front": false}  a la cola (front: delante, la que ha pedido el usuario;
                                                     también quita una fallida de la lista de fallidas)
    {"cmd": "remove", "files": [...]}              quitarlas de la cola
    {"cmd": "retry"}                                volver a intentar las fallidas
    {"cmd": "pause"} / {"cmd": "resume"}            pausa entre etapas (la app pausa mientras se juega)
    {"cmd": "status"}                               manda un aviso "queue"
    {"cmd": "quit"}                                 salir (también si se cierra stdin: la app se ha ido)
Avisos (stdout):
    {"event": "ready", "device": "cuda", "version": "0.3.2", "model": "best.pt" | null}
    {"event": "queue", "pending": 12, "failed": 1, "paused": false, "current": "D:/....mp3" | null}
    {"event": "start", "file": ...}
    {"event": "progress", "file": ..., "done": 0.45, "step": "..."}
    {"event": "done", "file": ..., "folder": "<carpeta de la chart>", "skipped": false}
    {"event": "error", "file": ..., "message": "..."}
    {"event": "paused"} / {"event": "idle"}

La cola se guarda en --queue (pendientes, fallidas y la que estaba en curso): si el motor se cae, al volver
sigue donde iba, y una canción que lo tumba dos veces pasa a fallidas.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .i18n import t

MAX_ATTEMPTS = 2  # una canción que tumba el motor tantas veces pasa a fallidas


class Quit(Exception):
    """Orden de salir a mitad de una canción: se queda en la cola para la próxima vez."""


class JobQueue:
    """Cola persistente: pendientes (en orden), fallidas (archivo -> motivo) y la que está en curso."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()  # se guarda desde el hilo de las órdenes (release) y desde el principal
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        self.pending: list[str] = list(d.get("pending", []))
        self.failed: dict[str, str] = dict(d.get("failed", {}))
        self.current: str | None = d.get("current")
        self.attempts = int(d.get("attempts", 0))
        if self.current and self.attempts >= MAX_ATTEMPTS:  # se cayó con ella otra vez
            self.fail(self.current, t("el motor se cerró varias veces con esta canción"))

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"pending": self.pending, "failed": self.failed, "current": self.current,
                                       "attempts": self.attempts}, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)

    def release(self) -> None:
        """Se sale a propósito (la app se cierra y puede matarlo a mitad): la canción en curso no cuenta como caída."""
        self.attempts = 0
        self.save()

    def add(self, files: list[str], front: bool = False) -> None:
        new = [f for f in dict.fromkeys(files) if front or f not in self.failed]
        for f in new:
            self.failed.pop(f, None)
        if front:
            self.pending = new + [f for f in self.pending if f not in new]
        else:
            self.pending += [f for f in new if f not in self.pending]
        self.save()

    def remove(self, files: list[str]) -> None:
        gone = set(files)
        self.pending = [f for f in self.pending if f not in gone]
        self.save()

    def retry(self) -> None:
        self.pending += [f for f in self.failed if f not in self.pending]
        self.failed.clear()
        self.save()

    def begin(self, f: str) -> None:
        self.attempts = self.attempts + 1 if self.current == f else 1
        self.current = f
        self.save()

    def finish(self, f: str) -> None:
        if f in self.pending:
            self.pending.remove(f)
        self.current, self.attempts = None, 0
        self.save()

    def fail(self, f: str, message: str) -> None:
        self.failed[f] = message
        self.finish(f)


def pick_device(want: str) -> str:
    if want != "auto":
        return want
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001 - sin torch que funcione, que lo diga generate
        return "cpu"


def ensure_ffmpeg(home: Path) -> None:
    """Demucs y Whisper llaman al programa ffmpeg: si no está en el sistema, el de imageio-ffmpeg."""
    if shutil.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg

        exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001 - sin ffmpeg casi todo va igual (libsndfile); los raros fallarán
        return
    bin_dir = home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / "ffmpeg.exe"
    if not target.exists():
        shutil.copy2(exe, target)
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


class Engine:
    def __init__(self, jobs: JobQueue, out_root: Path, model: Path | None, device: str, emit, lyrics: bool = True,
                 generate_fn=None, keep_stems: bool = False):
        """emit(dict): manda un aviso. generate_fn: la de cli (los tests ponen otra). keep_stems: guardar las
        pistas de Demucs (~50 MB por canción; sirven para rehacer la letra o entrenar, no para jugar)."""
        self.jobs, self.out_root, self.model, self.device = jobs, out_root, model, device
        self.emit, self.lyrics, self.keep_stems = emit, lyrics, keep_stems
        self.commands: queue.SimpleQueue[dict] = queue.SimpleQueue()
        self.paused = False
        self.quit = False
        self._idle_sent = False
        if generate_fn is None:
            from .cli import generate as generate_fn
        self.generate = generate_fn

    # ---------- órdenes ----------

    def handle(self, c: dict) -> None:
        cmd = c.get("cmd")
        files = [str(f) for f in c.get("files", [])]
        if cmd == "add":
            self.jobs.add(files, bool(c.get("front")))
        elif cmd == "remove":
            self.jobs.remove(files)
        elif cmd == "retry":
            self.jobs.retry()
        elif cmd == "pause":
            self.paused = True
        elif cmd == "resume":
            self.paused = False
        elif cmd == "quit":
            self.quit = True
            return
        elif cmd != "status":
            self.emit({"event": "error", "file": None, "message": t("orden desconocida: {cmd}", cmd=cmd)})
            return
        self._idle_sent = False
        self.status()

    def status(self) -> None:
        j = self.jobs
        self.emit({"event": "queue", "pending": len(j.pending), "failed": len(j.failed), "paused": self.paused,
                   "current": j.current})

    def poll(self, timeout: float | None) -> None:
        """Atiende las órdenes que haya; con timeout, espera hasta esa cantidad de segundos a la primera."""
        try:
            c = self.commands.get(timeout=timeout) if timeout else self.commands.get_nowait()
        except queue.Empty:
            return
        self.handle(c)
        while not self.quit:
            try:
                self.handle(self.commands.get_nowait())
            except queue.Empty:
                return

    # ---------- trabajo ----------

    def on_step(self, file: str, done: float, step: str) -> None:
        """Entre etapas de una canción: órdenes nuevas, la pausa y el progreso."""
        self.poll(None)
        if self.paused and not self.quit:
            self.emit({"event": "paused"})
            while self.paused and not self.quit:
                self.poll(1.0)
        if self.quit:
            raise Quit
        self.emit({"event": "progress", "file": file, "done": round(done, 3), "step": step})

    def process(self, file: str) -> None:
        from .audio import sha256_file
        from .cli import out_dir_for

        self.jobs.begin(file)
        self.emit({"event": "start", "file": file})
        try:
            audio = Path(file)
            if not audio.is_file():
                raise FileNotFoundError(t("no existe: {path}", path=file))
            out = out_dir_for(audio, sha256_file(audio), self.out_root)
            r = self.generate(audio, self.out_root, device=self.device, model_path=self.model, out_dir=out,
                              lyrics=self.lyrics, drop_stems=not self.keep_stems,
                              on_step=lambda d, s: self.on_step(file, d, s))
        except Quit:
            raise
        except Exception as e:  # noqa: BLE001 - una canción rara (o sin memoria de vídeo) no para la cola
            self.jobs.fail(file, f"{type(e).__name__}: {e}")
            self.emit({"event": "error", "file": file, "message": f"{type(e).__name__}: {e}"})
            _free_gpu()
            return
        self.jobs.finish(file)
        self.emit({"event": "done", "file": file, "folder": str(out), "skipped": r is None})

    def run(self) -> None:
        self.status()
        while not self.quit:
            waiting = self.paused or not self.jobs.pending
            if waiting and not self._idle_sent:
                self.emit({"event": "paused" if self.paused and self.jobs.pending else "idle"})
                self._idle_sent = True
            self.poll(1.0 if waiting else None)
            if self.quit or self.paused or not self.jobs.pending:
                continue
            self._idle_sent = False
            try:
                self.process(self.jobs.pending[0])
            except Quit:
                break
            self.status()


def _free_gpu() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def stdin_lines():
    """Las líneas de stdin sin dejar nunca una lectura esperando. En Windows, mientras un hilo está bloqueado
    leyendo la tubería de stdin, cargar ciertas DLL (OpenBLAS de scipy, con su propio arranque de C que mira los
    handles estándar) se queda colgado: se mira si ha llegado algo (PeekNamedPipe) y solo se lee lo que ya está."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    fd = sys.stdin.fileno()
    handle = msvcrt.get_osfhandle(fd)
    peek = ctypes.windll.kernel32.PeekNamedPipe
    avail = wintypes.DWORD()
    if not peek(handle, None, 0, None, ctypes.byref(avail), None):  # no es una tubería (a mano, en una consola)
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        yield from sys.stdin
        return
    buf = b""
    while peek(handle, None, 0, None, ctypes.byref(avail), None):  # falla al cerrarse: la app se ha ido
        if not avail.value:
            time.sleep(0.05)
            continue
        buf += os.read(fd, avail.value)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line.decode("utf-8", errors="replace")


def _read_commands(engine: Engine) -> None:
    for line in stdin_lines():
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except ValueError:
            engine.emit({"event": "error", "file": None, "message": t("orden que no es JSON: {line}", line=line[:80])})
            continue
        if cmd.get("cmd") == "quit":
            engine.jobs.release()
        engine.commands.put(cmd)
    engine.jobs.release()
    engine.commands.put({"cmd": "quit"})  # stdin cerrado: la app se ha ido


def main() -> int:
    parser = argparse.ArgumentParser(description=t("engine: el motor de generación que lanza la app (órdenes JSON "
                                                   "por stdin, avisos JSON por stdout)."),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queue", type=Path, required=True, help=t("archivo de la cola (se crea si no existe)"))
    parser.add_argument("--out", type=Path, required=True, help=t("carpeta de las charts"))
    parser.add_argument("--model", type=Path, help=t("modelo OnsetNet; sin él (o si no existe), las reglas"))
    parser.add_argument("--device", default="auto", choices=("auto", "cuda", "cpu"))
    parser.add_argument("--no-lyrics", action="store_true")
    parser.add_argument("--keep-stems", action="store_true", help=t("guardar las pistas de Demucs (~50 MB por canción)"))
    args = parser.parse_args()

    out = sys.stdout
    out.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stdout = sys.stderr  # lo que impriman generate y las librerías no se mezcla con los avisos
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    lock = threading.Lock()

    def emit(d: dict) -> None:
        with lock:
            out.write(json.dumps(d, ensure_ascii=False) + "\n")

    ensure_ffmpeg(args.queue.parent)
    device = pick_device(args.device)
    model = args.model if args.model and args.model.is_file() else None
    engine = Engine(JobQueue(args.queue), args.out, model, device, emit, lyrics=not args.no_lyrics,
                    keep_stems=args.keep_stems)
    emit({"event": "ready", "device": device, "version": __version__, "model": model.name if model else None})
    threading.Thread(target=_read_commands, args=(engine,), daemon=True, name="órdenes").start()
    t0 = time.perf_counter()
    engine.run()
    print(t("motor: fin tras {mins:.1f} min", mins=(time.perf_counter() - t0) / 60), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
