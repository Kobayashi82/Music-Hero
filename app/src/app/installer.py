"""Instalar el motor de generación en un PC nuevo (la app instalada, fase 7). Sin Qt: en un hilo, con el estado
para enseñarlo en los menús.

La app instalada lleva uv.exe, el código del generador (engine_src: pyproject, uv.lock y src) y OnsetNet. La primera
vez que hace falta (al añadir una carpeta de música o pedir una chart), si el usuario dice que sí:
1. Copia el código a ENGINE_DIR/project.
2. Elige la variante: CUDA si hay una NVIDIA con driver >= 580 (lo que pide CUDA 13); si no, CPU (torch de PyPI y
   onnxruntime sin GPU, sin el lockfile).
3. uv sync al entorno ENGINE_DIR/.venv: baja Python 3.12, torch y lo demás (~3 GB con CUDA, ~1 GB sin ella).
4. Los modelos (generator.fetch_models): Demucs, Beat This! y Whisper (~1,8 GB).
5. Copia OnsetNet y deja ENGINE_DIR/installed.json: ya se puede lanzar el motor (engine.engine_command).
Si algo falla (sin red, disco lleno...), se puede repetir: uv y las descargas siguen donde iban. El detalle va a
ENGINE_DIR/install.log.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .paths import ENGINE_DIR, FROZEN, REPO

BUNDLE = Path(getattr(sys, "_MEIPASS", REPO))  # lo que va dentro de la app (PyInstaller) o el repositorio
MIN_DRIVER = 580  # CUDA 13 (torch cu130)
NO_WINDOW = subprocess.CREATE_NO_WINDOW
SIZE_GB = {"cuda": 5, "cpu": 3}  # lo que baja, más o menos (motor + modelos)


def installed(engine_dir: Path = ENGINE_DIR) -> bool:
    return (engine_dir / "installed.json").exists() and (engine_dir / ".venv" / "Scripts" / "python.exe").exists()


def needed() -> bool:
    """La app instalada sin motor todavía (en desarrollo se usa el del repositorio con uv)."""
    return FROZEN and not installed()


def driver_version() -> int | None:
    """Versión principal del driver de NVIDIA (617 de 617.42); None si no hay NVIDIA."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW).stdout
        return int(out.strip().splitlines()[0].split(".")[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def cpu_pyproject(text: str) -> str:
    """El pyproject del generador sin la GPU: torch de PyPI (sin el índice de CUDA) y onnxruntime normal."""
    text = re.sub(r"\[tool\.uv\.sources\][^\[]*", "", text)
    text = re.sub(r"\[\[tool\.uv\.index\]\][^\[]*", "", text)
    text = re.sub(r"#[^\n]*CUDA[^\n]*\n", "", text)
    return text.replace('"onnxruntime-gpu>=', '"onnxruntime>=')


class EngineInstaller:
    def __init__(self, engine_dir: Path = ENGINE_DIR, source: Path | None = None, uv: str | None = None,
                 onsetnet: Path | None = None):
        """source: código del generador (engine_src en la app; generator/ en el repositorio)."""
        self.engine_dir = engine_dir
        self.source = source or (BUNDLE / "engine_src" if FROZEN else REPO / "generator")
        self.uv = uv or (str(BUNDLE / "uv.exe") if FROZEN else shutil.which("uv") or "uv")
        self.onsetnet = onsetnet or (BUNDLE / "models" / "onsetnet.pt" if FROZEN else REPO / "models" / "best.pt")
        self.state = "idle"  # idle | running | done | error
        self.step = ""
        self.done = 0.0  # 0..1 (aproximado: uv no dice cuánto le falta)
        self.error = ""
        self.variant = ""
        self.log = engine_dir / "install.log"
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.state == "running":
            return
        self.state, self.error, self.done = "running", "", 0.0
        self._thread = threading.Thread(target=self._run, daemon=True, name="instalar motor")
        self._thread.start()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    # ---------- pasos ----------

    def _run(self) -> None:
        self.engine_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.log, "a", encoding="utf-8") as log:
                log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                self._install(log)
            self.state, self.step, self.done = "done", "Motor listo", 1.0
        except Exception as e:  # noqa: BLE001 - sin red, disco lleno...: se enseña y se puede repetir
            self.state, self.error = "error", f"{e}"

    def _install(self, log) -> None:
        project = self.engine_dir / "project"
        self.step = "Preparando el motor"
        shutil.copytree(self.source, project, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.egg-info", "*.pyc"))
        drv = driver_version()
        self.variant = "cuda" if drv is not None and drv >= MIN_DRIVER else "cpu"
        log.write(f"driver NVIDIA: {drv}; variante: {self.variant}\n")
        if self.variant == "cpu":
            pp = project / "pyproject.toml"
            pp.write_text(cpu_pyproject(pp.read_text(encoding="utf-8")), encoding="utf-8")
            (project / "uv.lock").unlink(missing_ok=True)

        self.step = "Descargando el motor (Python, torch...)"
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        env |= {"UV_PROJECT_ENVIRONMENT": str(self.engine_dir / ".venv"), "UV_PYTHON_PREFERENCE": "only-managed"}
        cmd = [self.uv, "sync", "--project", str(project), "--python", "3.12", "--no-dev"]
        if self.variant == "cuda":
            cmd.append("--locked")
        self._stream(cmd, env, log, self._uv_line)
        self.done = 0.6

        self.step = "Descargando los modelos"
        from .engine import model_env

        py = self.engine_dir / ".venv" / "Scripts" / "python.exe"
        env |= model_env(self.engine_dir)
        sizes: dict[str, int] = {}
        got: dict[str, int] = {}
        failed: list[str] = []

        def on_line(line: str) -> None:
            try:
                ev = json.loads(line)
            except ValueError:
                return
            kind = ev.get("event")
            if kind == "plan":
                sizes.update({f["name"]: f["size"] for f in ev["files"]})
            elif kind == "progress":
                got[ev["name"]] = ev["done"]
                sizes.setdefault(ev["name"], ev["total"])
                total = sum(sizes.values()) or 1
                self.done = 0.6 + 0.4 * min(1.0, sum(got.values()) / total)
                self.step = f"Descargando {ev['name']} ({ev['done'] >> 20} de {sizes[ev['name']] >> 20} MB)"
            elif kind == "error":
                failed.append(ev["message"])
        self._stream([str(py), "-m", "generator.fetch_models"], env, log, on_line, stdout_events=True)
        if failed:
            raise RuntimeError(failed[-1])

        target = self.engine_dir / "models" / "onsetnet.pt"
        if self.onsetnet.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.onsetnet, target)
        (self.engine_dir / "installed.json").write_text(json.dumps({
            "variant": self.variant, "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model": target.name if target.exists() else None}, indent=1), encoding="utf-8")

    def _uv_line(self, line: str) -> None:
        line = line.strip()
        m = re.match(r"(Downloading|Downloaded|Installed|Prepared|Using CPython|Resolved)\s+(.*)", line)
        if m:
            self.step = {"Downloading": "Descargando", "Downloaded": "Descargado", "Installed": "Instalado",
                         "Prepared": "Preparado", "Using CPython": "Python", "Resolved": "Resuelto"}[m.group(1)] \
                + " " + m.group(2)[:60]
            if m.group(1) in ("Downloaded", "Prepared"):
                self.done = min(0.55, self.done + 0.01)

    def _stream(self, cmd: list[str], env: dict, log, on_line, stdout_events: bool = False) -> None:
        """Lanza cmd y pasa cada línea a on_line (stdout si stdout_events; si no, stderr, que es donde habla uv)."""
        log.write("$ " + " ".join(cmd) + "\n")
        log.flush()
        p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT if not stdout_events
                             else log, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        for line in p.stdout:
            log.write(line)
            on_line(line)
        if p.wait() != 0:
            raise RuntimeError(f"{Path(cmd[0]).name} terminó con error {p.returncode} (ver {self.log})")
