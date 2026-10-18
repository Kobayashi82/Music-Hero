"""Cliente del motor (app/engine.py) con un motor de mentira que habla el mismo protocolo.

    uv run --project app --with pytest pytest app/tests
"""

import sys
import time

from app.engine import RESTART_DELAYS_S, EngineClient

FAKE = r'''
import json, sys
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
crash = "--crash" in sys.argv
def emit(**d): print(json.dumps(d, ensure_ascii=False))
emit(event="ready", device="cpu", version="x", model=None)
pending = []
for line in sys.stdin:
    c = json.loads(line)
    if c["cmd"] == "quit":
        break
    if c["cmd"] == "add":
        pending = c["files"] + pending if c.get("front") else pending + c["files"]
        emit(event="queue", pending=len(pending), failed=0, paused=False, current=None)
        if crash:
            sys.exit(3)
        f = pending.pop(0)
        emit(event="start", file=f)
        emit(event="progress", file=f, done=0.5, step="mitad")
        emit(event="done", file=f, folder="x", skipped=False)
        emit(event="idle")
    if c["cmd"] == "pause":
        emit(event="paused")
'''


def client(tmp_path, *extra):
    script = tmp_path / "fake_engine.py"
    script.write_text(FAKE, encoding="utf-8")
    return EngineClient(lambda: ([sys.executable, str(script), *extra], None, tmp_path), log=tmp_path / "engine.log")


def wait_for(c: EngineClient, kind: str, timeout: float = 15.0) -> list[dict]:
    seen, end = [], time.monotonic() + timeout
    while time.monotonic() < end:
        seen += c.poll()
        if any(e.get("event") == kind for e in seen):
            return seen
        time.sleep(0.02)
    raise AssertionError(f"no llegó {kind}: {seen}")


def test_lanza_al_pedir_algo_y_sigue_el_progreso(tmp_path):
    c = client(tmp_path)
    assert not c.state.running
    c.add(["a.mp3"], front=True)
    seen = wait_for(c, "idle")
    kinds = [e["event"] for e in seen]
    assert kinds[:2] == ["ready", "queue"] and "done" in kinds
    assert c.state.device == "cpu" and c.state.current is None and c.state.running
    c.set_paused(True)
    wait_for(c, "paused")
    assert c.state.paused
    c.stop()
    wait_for(c, "exit")
    assert not c.state.running and c.state.error == ""  # parado a propósito: no es una caída


def test_si_se_cae_se_relanza(tmp_path):
    c = client(tmp_path, "--crash")
    c.add(["a.mp3"])
    wait_for(c, "exit")
    assert not c.state.running and "se cerró" in c.state.error
    c.poll(time.monotonic() + RESTART_DELAYS_S[0] + 1)  # pasado el primer plazo: otra vez
    assert c.state.running
    c.stop()


def test_sin_motor_no_revienta(tmp_path):
    c = EngineClient(lambda: None, log=tmp_path / "engine.log")
    assert not c.available()
    c.add(["a.mp3"])
    assert not c.state.running and "no se puede lanzar" in c.state.error
