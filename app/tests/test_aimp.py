"""Seguir a AIMP sin AIMP: pausar y seguir con sus manías. uv run --project app --with pytest pytest app/tests"""

import time

from app.aimp import CMD_PAUSE, CMD_PLAY, PAUSED, PLAYING, AimpPlayer, Track


class FakeAimp:
    """Como AIMP: PAUSE alterna y PLAY con la canción sonando la empieza de nuevo."""

    def __init__(self):
        self._state, self.pos, self.sent = PLAYING, 50000, []

    def state(self):
        return self._state

    def position(self):
        return self.pos

    def seek(self, ms):
        self.pos = ms

    def command(self, cmd):
        self.sent.append(cmd)
        if cmd == CMD_PAUSE:
            self._state = PAUSED if self._state == PLAYING else PLAYING
        elif cmd == CMD_PLAY:
            if self._state == PLAYING:
                self.pos = 0  # ¡la reinicia!
            self._state = PLAYING


def wait_for(cond, timeout=2.0):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end and not cond():
        time.sleep(0.01)
    return cond()


def make(monkeypatch):
    monkeypatch.setattr(AimpPlayer, "CMD_WAIT_S", 0.05)
    aimp = FakeAimp()
    return aimp, AimpPlayer(aimp, Track("x.mp3", "x", "", "", 200000))


def test_pausar_dos_veces_no_reanuda(monkeypatch):
    aimp, p = make(monkeypatch)
    p.pause()
    assert not p.playing  # para el juego, en pausa ya al pedirlo
    p.pause()
    assert wait_for(lambda: aimp.state() == PAUSED and p._want is None)
    p.pause()
    time.sleep(0.2)
    assert aimp.state() == PAUSED and aimp.sent == [CMD_PAUSE]
    p.close()


def test_seguir_no_reinicia(monkeypatch):
    aimp, p = make(monkeypatch)
    p.play()  # ya sonando: nada (PLAY la empezaría de nuevo)
    time.sleep(0.2)
    assert aimp.sent == [] and aimp.pos == 50000
    p.pause()
    assert wait_for(lambda: aimp.state() == PAUSED)
    p.play()  # desde la pausa se sigue con PAUSE, que alterna
    assert wait_for(lambda: aimp.state() == PLAYING and p._want is None)
    assert CMD_PLAY not in aimp.sent and aimp.pos == 50000
    p.close()


def test_salto_desde_aimp(monkeypatch):
    aimp, p = make(monkeypatch)
    time.sleep(0.05)
    aimp.pos = 120000
    assert wait_for(lambda: p._seek is not None or p.clock.seeked_to is not None)
    assert p.take_seek() == 120000 and p.take_seek() is None
    p.close()
