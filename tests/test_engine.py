"""Motor de generación (generator/engine.py) con un generate de mentira: cola, prioridad, pausa y caídas.

    uv run --project generator --with pytest pytest tests
"""

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from generator.engine import MAX_ATTEMPTS, Engine, JobQueue, Quit


def songs(tmp_path: Path, n: int) -> list[str]:
    out = []
    for i in range(n):
        f = tmp_path / f"canción {i}.mp3"
        f.write_bytes(bytes([i]) * 100)  # contenido distinto: hash distinto
        out.append(str(f))
    return out


class Events(list):
    """Los avisos del motor; al quedarse sin trabajo («idle»), se le manda salir."""

    engine = None

    def __call__(self, ev: dict) -> None:
        self.append(ev)
        if ev["event"] == "idle" and self.engine is not None:
            self.engine.commands.put({"cmd": "quit"})


def make_engine(tmp_path: Path, fake=None):
    events = Events()
    calls = []

    def generate(audio, out_root, **kw):
        calls.append(str(audio))
        if fake:
            return fake(audio, kw)
        for d in (0.4, 0.8, 1.0):
            kw["on_step"](d, f"etapa {d}")
        kw["out_dir"].mkdir(parents=True, exist_ok=True)
        return kw["out_dir"]

    e = Engine(JobQueue(tmp_path / "cola.json"), tmp_path / "charts", None, "cpu", events, generate_fn=generate)
    events.engine = e
    return e, events, calls


def test_cola_en_orden_y_la_pedida_delante(tmp_path):
    a, b, c = songs(tmp_path, 3)
    e, events, calls = make_engine(tmp_path)
    e.handle({"cmd": "add", "files": [a, b]})
    e.handle({"cmd": "add", "files": [c, a], "front": True})  # c y a delante, sin repetir a
    assert e.jobs.pending == [c, a, b]
    e.run()  # sale al acabar la cola
    assert calls == [c, a, b]
    done = [ev for ev in events if ev["event"] == "done"]
    assert [d["file"] for d in done] == [c, a, b] and all(Path(d["folder"]).is_dir() for d in done)
    assert any(ev["event"] == "progress" and ev["done"] == 0.4 for ev in events)
    assert JobQueue(tmp_path / "cola.json").pending == []  # guardada


def test_una_que_falla_no_para_la_cola_y_no_se_reintenta_sola(tmp_path):
    a, b = songs(tmp_path, 2)

    def fake(audio, kw):
        if str(audio) == a:
            raise RuntimeError("CUDA out of memory")
        return kw["out_dir"]
    e, events, calls = make_engine(tmp_path, fake)
    e.handle({"cmd": "add", "files": [a, b]})
    e.run()
    assert calls == [a, b]
    assert "CUDA out of memory" in e.jobs.failed[a]
    e.jobs.add([a])  # al volver a escanear la biblioteca: no se reintenta sola
    assert e.jobs.pending == []
    e.jobs.add([a], front=True)  # la pide el usuario: sí
    assert e.jobs.pending == [a] and a not in e.jobs.failed


def test_pausa_entre_etapas_y_salir_a_mitad_la_deja_en_cola(tmp_path):
    (a,) = songs(tmp_path, 1)
    e, events, calls = make_engine(tmp_path)
    e.handle({"cmd": "add", "files": [a]})
    e.paused = True
    threading.Timer(0.3, lambda: e.commands.put({"cmd": "quit"})).start()
    with pytest.raises(Quit):  # en pausa en la primera etapa, hasta que llega la orden de salir
        e.on_step(a, 0.4, "x")
    assert {"event": "paused"} in events
    e.jobs.begin(a)
    again = JobQueue(tmp_path / "cola.json")
    assert again.pending == [a] and again.current == a


def test_la_que_tumba_el_motor_dos_veces_pasa_a_fallidas(tmp_path):
    (a,) = songs(tmp_path, 1)
    q = JobQueue(tmp_path / "cola.json")
    q.add([a])
    for _ in range(MAX_ATTEMPTS):
        q.begin(a)  # empieza y "se cae" (no llega a finish)
        q = JobQueue(tmp_path / "cola.json")
    assert q.pending == [] and a in q.failed


def test_proceso_real_habla_json(tmp_path):
    """El motor de verdad (sin canciones): avisos JSON por stdout, órdenes por stdin, sale al cerrar stdin."""
    p = subprocess.run([sys.executable, "-m", "generator.engine", "--queue", str(tmp_path / "cola.json"),
                        "--out", str(tmp_path / "charts"), "--device", "cpu", "--model", str(tmp_path / "no.pt")],
                       input='{"cmd": "status"}\n', capture_output=True, text=True, encoding="utf-8", timeout=120)
    events = [json.loads(line) for line in p.stdout.splitlines()]
    assert p.returncode == 0
    assert events[0]["event"] == "ready" and events[0]["model"] is None
    assert {"event": "queue", "pending": 0, "failed": 0, "paused": False, "current": None} in events
