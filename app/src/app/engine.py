"""El motor de generación (generator/engine.py) visto desde la app. Sin Qt: Session lo atiende cada fotograma.

Se lanza solo cuando hay trabajo (sin ventana y con prioridad baja), se le pasan canciones, se pausa mientras
se juega y, si se cae (o se queda sin memoria de vídeo y lo tumba), se vuelve a lanzar: la cola la guarda el
propio motor en disco, así que sigue donde iba. Tras unos minutos sin trabajo se cierra para liberar memoria.
Lo que imprime el motor (el detalle de cada canción) va a ENGINE_LOG.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .i18n import t
from .paths import CHARTS_DIR, DATA, ENGINE_DIR, ENGINE_LOG, FROZEN, MODEL, QUEUE_FILE, REPO

RESTART_DELAYS_S = (5, 30, 120)  # si se cae: espera antes de cada nuevo intento; luego, hasta que se le pida algo
IDLE_QUIT_S = 300  # sin trabajo: se cierra (vuelve en cuanto haga falta)
LOG_MAX = 5 << 20  # el log pasa a .old al llegar a 5 MB


def model_env(engine_dir: Path) -> dict[str, str]:
    """Dónde guardan sus modelos las librerías del motor instalado (Demucs, Beat This!, Whisper)."""
    models = engine_dir / "models"
    return {"TORCH_HOME": str(models / "torch"), "XDG_CACHE_HOME": str(models / "cache"),
            "HF_HOME": str(models / "hf")}


def engine_command() -> tuple[list[str], dict[str, str], Path] | None:
    """(orden, entorno, carpeta) para lanzar el motor; None si no se puede (sin uv, o sin instalar)."""
    args = ["--queue", str(QUEUE_FILE), "--out", str(CHARTS_DIR), "--model", str(MODEL)]
    if DATA == REPO / "out":  # en el repositorio se guardan las pistas (para rehacer la letra, entrenar...)
        args.append("--keep-stems")
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}  # el del juego no es el del generador
    if FROZEN:
        from .installer import installed

        if not installed():  # se instala la primera vez que hace falta (installer.py)
            return None
        py = ENGINE_DIR / ".venv" / "Scripts" / "python.exe"
        return [str(py), "-m", "generator.engine", *args], env | model_env(ENGINE_DIR), ENGINE_DIR
    uv = shutil.which("uv")
    if uv is None:
        return None
    return [uv, "run", "--project", str(REPO / "generator"), "engine", *args], env, REPO


@dataclass
class EngineState:
    running: bool = False
    device: str = ""  # "cuda" | "cpu" (lo dice el motor al arrancar)
    pending: int = 0
    failed: int = 0
    paused: bool = False
    current: str | None = None  # la canción que está haciendo
    done: float = 0.0  # de la actual, 0..1
    step: str = ""
    error: str = ""  # el último problema del propio motor (no el de una canción)
    finished: int = 0  # hechas desde que se abrió el juego
    eta_s: float | None = None  # lo que falta para acabar la cola (None: aún no se sabe)


class EngineClient:
    def __init__(self, command=engine_command, log: Path = ENGINE_LOG, queue_file: Path = QUEUE_FILE):
        """command(): (orden, entorno, carpeta) o None; los tests ponen otra."""
        self.command = command
        self.log = log
        self.queue_file = queue_file
        self._snapshot: tuple[float, set[str], dict[str, str]] = (-1.0, set(), {})
        self.state = EngineState()
        self._proc: subprocess.Popen | None = None
        self._events: queue.SimpleQueue[dict] = queue.SimpleQueue()
        self._want_paused = False
        self._stopping = False
        self._restarts = 0
        self._restart_at: float | None = None
        self._idle_since: float | None = None
        self._active_s = 0.0  # lo que lleva la canción actual trabajando (sin las pausas)
        self._tick: float | None = None
        self._durations: list[float] = []  # lo que tardaron las últimas (para la estimación)

    # ---------- órdenes ----------

    def available(self) -> bool:
        return self.command() is not None

    def add(self, files: list[str], front: bool = False) -> None:
        if files:
            self._send({"cmd": "add", "files": files, "front": front})

    def remove(self, files: list[str]) -> None:
        if files and self._proc is not None:  # parado no hace falta: ya lo leerá de la cola al volver
            self._send({"cmd": "remove", "files": files}, start=False)

    def retry(self) -> None:
        self._send({"cmd": "retry"})

    def set_paused(self, paused: bool) -> None:
        if paused != self._want_paused:
            self._want_paused = paused
            if self._proc is not None:
                self._send({"cmd": "pause" if paused else "resume"}, start=False)

    def snapshot(self) -> tuple[set[str], dict[str, str]]:
        """(pendientes, fallidas -> motivo), leídas de la cola que guarda el motor (como mucho una vez por segundo),
        con las rutas normalizadas (os.path.normcase)."""
        now = time.monotonic()
        if now - self._snapshot[0] > 1.0:
            try:
                d = json.loads(self.queue_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                d = {}
            norm = os.path.normcase
            self._snapshot = (now, {norm(f) for f in d.get("pending", [])},
                              {norm(f): m for f, m in d.get("failed", {}).items()})
        return self._snapshot[1], self._snapshot[2]

    def start(self) -> bool:
        """Lo lanza (si no lo estaba): sigue con la cola que tenga guardada."""
        if self._proc is not None:
            return True
        cmd = self.command()
        if cmd is None:
            self.state.error = t("no se puede lanzar el motor (falta uv, o no está instalado)")
            return False
        argv, env, cwd = cmd
        self.log.parent.mkdir(parents=True, exist_ok=True)
        if self.log.exists() and self.log.stat().st_size > LOG_MAX:
            self.log.replace(self.log.with_suffix(".old.log"))
        flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        with open(self.log, "a", encoding="utf-8") as log:  # el proceso hereda su propia copia
            log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(argv)}\n")
            log.flush()
            try:
                self._proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                              stderr=log, text=True, encoding="utf-8", errors="replace", bufsize=1,
                                              creationflags=flags)
            except OSError as e:
                self.state.error = t("no se pudo lanzar el motor: {err}", err=e)
                return False
        self._stopping = False
        self._restart_at = None
        self._idle_since = None
        self.state.running, self.state.error = True, ""
        threading.Thread(target=self._read, args=(self._proc,), daemon=True, name="motor").start()
        if self._want_paused:
            self._send({"cmd": "pause"}, start=False)
        return True

    def stop(self, wait_s: float = 3.0) -> None:
        """Salir: termina la etapa en curso y sale (la canción a medias se queda en la cola); si tarda, se mata."""
        proc = self._proc
        if proc is None:
            return
        self._stopping = True
        self._send({"cmd": "quit"}, start=False)
        try:
            proc.wait(wait_s)
        except subprocess.TimeoutExpired:
            proc.kill()

    # ---------- cada fotograma ----------

    def poll(self, now: float | None = None) -> list[dict]:
        """Lo que ha dicho el motor desde la última vez (start, progress, done, error...), con el estado al día;
        también lo vuelve a lanzar si se cayó, y lo cierra si lleva rato sin trabajo."""
        now = time.monotonic() if now is None else now
        s = self.state
        if self._tick is not None and s.current and not s.paused:
            self._active_s += now - self._tick
        self._tick = now
        out = []
        while True:
            try:
                ev = self._events.get_nowait()
            except queue.Empty:
                break
            self._apply(ev, now)
            out.append(ev)
        s.eta_s = self._eta()
        if self._restart_at is not None and now >= self._restart_at:
            self.start()
        if self._idle_since is not None and now - self._idle_since > IDLE_QUIT_S and self._proc is not None:
            self.stop(wait_s=0.5)
        return out

    # ---------- interno ----------

    def _eta(self) -> float | None:
        """Lo que falta: la actual por su avance y las de la cola a lo que tardan de media (la mediana de las
        últimas; sin ninguna hecha aún, lo que va a tardar la actual según su avance)."""
        s = self.state
        if not s.pending:
            return None
        guess = self._active_s / s.done if s.current and s.done >= 0.15 else None
        per = sorted(self._durations)[len(self._durations) // 2] if self._durations else guess
        if per is None:
            return None
        current = (guess if guess is not None else per) * (1 - s.done) if s.current else 0.0
        return current + per * (s.pending - (1 if s.current else 0))

    def _send(self, cmd: dict, start: bool = True) -> None:
        if self._proc is None and not (start and self.start()):
            return
        self._idle_since = None
        try:
            self._proc.stdin.write(json.dumps(cmd, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError):  # se acaba de caer: lo verá poll
            pass

    def _read(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            try:
                self._events.put(json.loads(line))
            except ValueError:
                continue
        self._events.put({"event": "exit", "code": proc.wait(), "proc": proc})

    def _apply(self, ev: dict, now: float) -> None:
        s = self.state
        kind = ev.get("event")
        if kind == "ready":
            s.device = ev.get("device", "")
            self._restarts = 0
        elif kind == "queue":
            s.pending, s.failed, s.paused, s.current = ev["pending"], ev["failed"], ev["paused"], ev["current"]
        elif kind == "start":
            s.current, s.done, s.step = ev["file"], 0.0, ""
            self._active_s = 0.0
        elif kind == "progress":
            s.done, s.step = ev["done"], ev["step"]
        elif kind in ("done", "error") and ev.get("file") == s.current:
            if kind == "done":
                s.finished += 1
                if not ev.get("skipped") and self._active_s > 5:  # las ya hechas (saltadas) no dicen nada
                    self._durations = (self._durations + [self._active_s])[-20:]
            s.current, s.done, s.step = None, 0.0, ""
        elif kind == "paused":
            s.paused = True
        elif kind == "idle":
            s.paused, s.current = False, None
            self._idle_since = now
        elif kind == "exit":
            if ev.get("proc") is not self._proc:
                return
            self._proc = None
            s.running, s.current, s.done, s.step = False, None, 0.0, ""
            if not self._stopping:  # se ha caído
                s.error = t("el motor se cerró (código {code}); detalles en {log}", code=ev["code"], log=self.log.name)
                if self._restarts < len(RESTART_DELAYS_S):
                    self._restart_at = now + RESTART_DELAYS_S[self._restarts]
                    self._restarts += 1
