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


def test_seguir_tras_una_pausa_no_es_un_salto(monkeypatch):
    """Los cambios de antes de la pausa no valen al seguir: adelantarían la estimación lo que durase la pausa."""
    from app.aimp import PositionClock

    now = [0.0]
    monkeypatch.setattr(PositionClock, "now", staticmethod(lambda: now[0]))
    aimp = FakeAimp()
    clock = PositionClock(aimp)
    for i in range(10):  # sonando: 30 ms cada 30 ms
        now[0], aimp.pos = i * 0.03, 50000 + i * 30
        clock.update()
    aimp._state = PAUSED
    for i in range(10, 200):  # 5 s en pausa
        now[0] = i * 0.03
        clock.update()
    aimp._state = PLAYING
    now[0], aimp.pos = 6.03, 50300
    clock.update()
    assert clock.seeked_to is None and abs(clock.estimate(6.03) - 50300) < 1


def test_el_retardo_nuevo_entra_poco_a_poco(monkeypatch):
    p = AimpPlayer(FakeAimp(), Track("x.mp3", "x", "", "", 200000), offset_ms=100.0)
    t0 = time.perf_counter()
    p.offset_ms = 120.0  # lo medido con el loopback
    assert p.offset_ms == 120.0
    assert 99 < p._offset_at(t0) < 101 and 109 < p._offset_at(t0 + p.OFFSET_GLIDE_S / 2) < 111
    assert p._offset_at(t0 + p.OFFSET_GLIDE_S + 0.1) == 120.0
    p.close()
