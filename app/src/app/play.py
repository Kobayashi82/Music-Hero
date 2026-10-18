"""play canción.mp3 | carpeta de chart -> juega la canción en el overlay, con el reproductor propio (fase 3).

Uso:
    uv run --project app play "D:/Programas/Multimedia/Musicas/Queen/Greatest Hits II/Queen - Hammer to Fall.mp3"
    uv run --project app play "out/charts/Queen - Hammer to Fall" --difficulty hard

Controles: ver app/inputs.py (A S D F G + flechas, o la guitarra de Wii; Espacio/Start pausa;
Ctrl+Alt+H muestra/oculta; Ctrl+Alt+Q sale). Ajustes en %APPDATA%/MusicHero/config.json.
"""

from __future__ import annotations

import argparse
import bisect
import signal
import sys
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QColor, QGuiApplication, QSurfaceFormat
from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface

from . import win32
from .chart import DIFF_NAMES, DIFFS, Chart, find_chart
from .config import Config
from .gameplay import HIT, MISSED, Game
from .inputs import Inputs
from .player import Player

QML = Path(__file__).with_name("qml") / "Highway.qml"
TRAVEL_MS = 1200.0  # del horizonte a la línea de golpeo con note_speed = 1
BEHIND_MS = 250.0  # lo que se sigue viendo por debajo de la línea
LEAD_IN_MS = 2500.0
RESUME_MS = 1500.0  # cuenta atrás al quitar la pausa


class Session(QObject):
    def __init__(self, chart: Chart, cfg: Config, difficulty: str, inputs: Inputs, view: QQuickView):
        super().__init__()
        self.chart, self.cfg, self.inputs, self.view = chart, cfg, inputs, view
        self.difficulty = difficulty if difficulty in chart.difficulties else next(iter(chart.difficulties))
        self.player = Player(chart.audio_file, cfg.audio_offset_ms, LEAD_IN_MS, cfg.volume)
        self.held = [False] * 5
        self.flash_t = [0.0] * 5
        self.miss_t = 0.0
        self.resume_at: float | None = None
        self.paused = False
        self.results = ""
        self.message = "; ".join(inputs.errors)
        self.beats = chart.beats
        self.beat_times = [b[0] for b in self.beats]
        self.new_game()
        self.player.play()

    # ---------- partida ----------

    def new_game(self) -> None:
        notes = self.chart.difficulties[self.difficulty]
        self.game = Game(notes)
        self.times = [n.time_ms for n in notes]
        self.max_sustain = max((n.sustain_ms for n in notes), default=0)
        self.results = ""

    def restart(self, paused: bool = False) -> None:
        self.player.pause()
        self.player.seek(-LEAD_IN_MS)
        self.new_game()
        self.paused, self.resume_at = paused, None
        if not paused:
            self.player.play()

    def set_paused(self, paused: bool) -> None:
        if paused:
            self.player.pause()
            self.paused, self.resume_at = True, None
        elif self.paused and self.resume_at is None:
            self.resume_at = time.perf_counter() + RESUME_MS / 1000

    def cycle_difficulty(self) -> None:
        avail = [d for d in DIFFS if d in self.chart.difficulties]
        self.difficulty = avail[(avail.index(self.difficulty) + 1) % len(avail)]
        self.cfg.difficulty = self.difficulty
        self.cfg.save()
        self.restart(paused=True)

    def toggle_visible(self) -> None:
        if self.view.isVisible():
            self.set_paused(True)
            self.inputs.set_game_keys(False)
            self.view.hide()
        else:
            self.view.show()
            win32.make_click_through(int(self.view.winId()))
            self.inputs.set_game_keys(True)

    # ---------- cada fotograma ----------

    def handle_inputs(self) -> None:
        for ev in self.inputs.drain():
            if ev.kind == "control":
                self.control(ev.value)
                continue
            if ev.kind == "fret":
                self.held[ev.value] = ev.down
            playing = self.player.playing and not self.results
            if not playing:
                if ev.kind == "fret":
                    (self.game.held.add if ev.down else self.game.held.discard)(ev.value)
                elif ev.kind == "strum" and (self.paused or self.results):
                    self.cycle_difficulty()
                continue
            t = self.player.position_ms(ev.t)
            if ev.kind == "fret":
                self.game.fret(ev.value, ev.down, t)
            elif ev.kind == "strum":
                self.game.strum(t)

    def control(self, name: str) -> None:
        if name == "quit":
            QGuiApplication.quit()
        elif name == "toggle":
            self.toggle_visible()
        elif name in ("pause", "start"):
            if self.results:
                self.restart()
            else:
                self.set_paused(not self.paused)
        elif name == "restart" or (name == "select" and (self.paused or self.results)):
            self.restart()
        elif name == "difficulty" and (self.paused or self.results):
            self.cycle_difficulty()

    def frame(self) -> dict:
        now = time.perf_counter()
        if self.resume_at is not None and now >= self.resume_at:
            self.resume_at, self.paused = None, False
            self.player.play()
        self.handle_inputs()
        t = self.player.position_ms(now)
        if self.player.playing:
            self.game.update(t)
        for kind, _, ns in self.game.events:
            if kind == "hit":
                for f in ns.note.frets:
                    self.flash_t[f] = now
            else:
                self.miss_t = now
        self.game.events.clear()
        if not self.results and self.game.finished and t > self.chart.duration_ms - 500 or (
                not self.results and self.player.finished):
            self.results = self.summary()
            self.player.pause()

        tv = self.player.position_ms(now + self.cfg.video_offset_ms / 1000)
        travel = TRAVEL_MS / max(0.3, self.cfg.note_speed)
        notes = []
        start = bisect.bisect_left(self.times, tv - BEHIND_MS - self.max_sustain)
        for ns in self.game.notes[start:]:
            n = ns.note
            u = (n.time_ms - tv) / travel
            if u > 1.02:
                break
            u_end = min(1.02, (n.time_ms + n.sustain_ms - tv) / travel) if n.sustain_ms else u
            if u_end < -BEHIND_MS / travel or (ns.state == HIT and not n.sustain_ms):
                continue
            state = ns.state
            if ns.state == HIT and not ns.sustaining:
                if ns.sustain_until >= n.time_ms + n.sustain_ms - 1:
                    continue  # sustain completo
                state = MISSED  # soltado antes: la cola en gris
            for f in n.frets:
                notes += [f, max(u, -0.25), u_end, state, int(n.hopo), int(ns.sustaining)]
            if len(notes) >= 6 * 200:
                break
        beats = []
        i = bisect.bisect_left(self.beat_times, tv - BEHIND_MS)
        for bt, bar in self.beats[i:i + 32]:
            u = (bt - tv) / travel
            if u > 1.02:
                break
            beats += [u, int(bar)]

        st = self.game.stats
        status = ""
        if self.paused:
            status = f"PAUSA · {DIFF_NAMES[self.difficulty]}"
        countdown = 0.0
        if self.resume_at is not None:
            countdown = self.resume_at - now
        elif self.player.playing and t < 0 and not self.game.stats.hits:
            countdown = -t / 1000
        hint = "Espacio/Start: seguir · Retroceso/Select: reiniciar · Tab/strum: dificultad" if (self.paused or self.results) else ""
        return {
            "notes": notes, "beats": beats, "held": self.held,
            "flash": [max(0.0, 1 - (now - ft) / 0.15) for ft in self.flash_t],
            "missFlash": max(0.0, 1 - (now - self.miss_t) / 0.25),
            "score": st.score, "streak": st.streak, "mult": st.multiplier, "accuracy": st.accuracy,
            "title": f"{self.chart.artist} – {self.chart.title} · {DIFF_NAMES[self.difficulty]}",
            "progress": max(0.0, min(1.0, t / max(1, self.chart.duration_ms))),
            "countdown": countdown, "status": status, "results": self.results,
            "message": " · ".join(filter(None, [self.message, hint])), "opacity": self.cfg.opacity,
        }

    def summary(self) -> str:
        st = self.game.stats
        total = len(self.game.notes)
        lines = [f"<b>{DIFF_NAMES[self.difficulty]}: {st.hits}/{total} notas ({st.accuracy:.0%})</b>",
                 f"Puntos: {round(st.score):,}".replace(",", "."),
                 f"Mejor racha: {st.best_streak} · Strums de más: {st.overstrums}"]
        if len(st.offsets) >= 20:
            offs = sorted(st.offsets)
            med = offs[len(offs) // 2]
            when = "tarde" if med > 0 else "pronto"
            lines.append(f"Tus strums van de media {abs(med):.0f} ms {when}" +
                         (" (si te pasa siempre, ajusta audio_offset_ms)" if abs(med) > 25 else ""))
        lines.append("Espacio/Start: otra vez · Tab/strum: dificultad · Ctrl+Alt+Q: salir")
        return "<br>".join(lines)


class Bridge(QObject):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.session: Session | None = None

    @Property(int, constant=True)
    def highwayWidth(self) -> int:  # noqa: N802 - nombre para QML
        return self.cfg.highway_width

    @Slot(result="QVariantMap")
    def tick(self) -> dict:
        return self.session.frame() if self.session else {}


def make_view(cfg: Config, app: QGuiApplication, bridge: Bridge) -> QQuickView:
    view = QQuickView()
    view.setFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                  | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
    view.setColor(QColor(0, 0, 0, 0))
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.setProperty("_q_showWithoutActivating", True)
    geo = app.primaryScreen().availableGeometry()
    w = min(geo.width(), cfg.highway_width + 420)  # sitio para el marcador a la derecha
    x = {"left": geo.x(), "right": geo.x() + geo.width() - w}.get(cfg.position, geo.x() + (geo.width() - w) // 2)
    view.setGeometry(x, geo.y(), w, geo.height())
    view.rootContext().setContextProperty("bridge", bridge)
    view.setSource(QUrl.fromLocalFile(str(QML)))
    for err in view.errors():
        print("QML:", err.toString())
    return view


def resolve(path: Path) -> Chart:
    if path.is_file() and path.suffix.lower() != ".json":
        folder = find_chart(path)
        if folder is None:
            sys.exit(f"No hay chart para {path.name}; genérala con: uv run --project generator generate \"{path}\"")
        chart = Chart.load(folder)
        chart.audio_file = path
        return chart
    chart = Chart.load(path)
    if not chart.audio_file.exists():
        sys.exit(f"No encuentro el audio de la chart: {chart.audio_file}")
    return chart


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("song", type=Path, help="audio (busca su chart en out/charts) o carpeta de chart")
    parser.add_argument("--difficulty", choices=DIFFS, help="por defecto, la última usada")
    parser.add_argument("--speed", type=float, help="velocidad de las notas (1 = normal)")
    parser.add_argument("--screenshot", type=Path, help="guarda una captura a los N s (--screenshot-at)")
    parser.add_argument("--screenshot-at", type=float, default=8.0)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    args = parser.parse_args()

    cfg = Config.load()
    if args.speed:
        cfg.note_speed = args.speed
    chart = resolve(args.song)

    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QGuiApplication(sys.argv)
    bridge = Bridge(cfg)
    view = make_view(cfg, app, bridge)

    inputs = Inputs()
    inputs.start()
    inputs.set_game_keys(True)
    for e in inputs.errors:
        print("aviso:", e)
    bridge.session = Session(chart, cfg, args.difficulty or cfg.difficulty, inputs, view)

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer()  # deja que Python atienda Ctrl+C
    keepalive.start(200)
    keepalive.timeout.connect(lambda: None)
    topmost = QTimer()
    topmost.timeout.connect(lambda: view.isVisible() and win32.bring_to_top(int(view.winId())))
    topmost.start(500)
    if args.screenshot:
        QTimer.singleShot(int(args.screenshot_at * 1000),
                          lambda: app.primaryScreen().grabWindow(0).save(str(args.screenshot)))

    view.show()
    win32.make_click_through(int(view.winId()))
    print(f"{chart.artist} - {chart.title} ({DIFF_NAMES[bridge.session.difficulty]}). "
          "Espacio pausa, Ctrl+Alt+H oculta, Ctrl+Alt+Q sale.")
    try:
        return app.exec()
    finally:
        inputs.stop()
        bridge.session.player.close()


if __name__ == "__main__":
    sys.exit(main())
