"""play [canción.mp3 | carpeta de chart] -> juega en el overlay, con el reproductor propio (fase 3).

Uso:
    uv run --project app play            (abre el selector de canciones, en la última que jugaste)
    uv run --project app play "D:/Programas/Multimedia/Musicas/Queen/Greatest Hits II/Queen - Hammer to Fall.mp3"
    uv run --project app play "out/charts/Queen - Hammer to Fall" --difficulty hard
    uv run --project app play --hidden   (en segundo plano: Ctrl+Alt+H lo muestra; si suena AIMP, lo sigue)

Con AIMP sonando (al abrir, al mostrarlo con Ctrl+Alt+H o con «Seguir a AIMP» en la pausa), el juego sigue a
AIMP: su posición es el reloj, cada canción que ponga carga su chart, los saltos en AIMP se respetan y la pausa
del juego pausa AIMP. Si la canción no tiene chart, la pausa ofrece generarla en segundo plano.

Controles: ver app/inputs.py (A S D F G + flechas, o la guitarra de Wii). + o Espacio abren el menú
(dificultad, ajustes, calibración); − o Tab cambian de dificultad sin parar; levantar la guitarra o E activan
el star power. Ctrl+Alt+H muestra/oculta;
Ctrl+Alt+Q sale. Ajustes en %APPDATA%/MusicHero/config.json (se guardan solos desde el menú).
"""

from __future__ import annotations

import argparse
import bisect
import os
import random
import re
import signal
import sys
import threading
import time
from pathlib import Path

import numpy as np

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap, QPolygonF, QSurfaceFormat
from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from . import calibration, installer, loopback, pairing, starpower, win32
from .aimp import CMD_NEXT, CMD_PAUSE, CMD_PREV, PLAYING, Aimp, AimpPlayer, Track
from .chart import DIFF_NAMES, DIFFS, Chart, find_chart
from .config import Config
from .engine import EngineClient
from .gameplay import HIT, MISSED, SKIPPED, Game
from .i18n import LANGS, N_, TrDict, lang, set_language, t
from .inputs import ACTION_NAMES, ACTIONS, BACKSPACE, GLOBAL_ACTIONS, Inputs, assign, keymap
from .library import Entry, MusicWatcher, group, in_dirs, norm, pending_entries, scan, search, without_chart
from .lyrics import Lyrics
from .menu import Menu, Option, SearchMenu, cycler, sep_above, stepper
from .paths import APP_LOG, CHARTS_DIR, FROZEN
from .player import Player
from .records import Play, Records
from .sprites import SpriteProvider

QML = Path(__file__).with_name("qml") / "Highway.qml"
TRAVEL_MS = 1200.0  # del horizonte a la línea de golpeo con note_speed = 1
BEHIND_MS = 250.0  # lo que se sigue viendo por debajo de la línea
LEAD_IN_MS = 2500.0
RESUME_MS = 1500.0  # cuenta atrás al quitar la pausa
SWITCH_AHEAD_MS = 400.0  # al cambiar de dificultad jugando, las notas más cercanas no cuentan
TOAST_S = 2.5
SIDE_MARGIN = 640  # la ventana es la autopista más esto (la mitad a cada lado): sitio para el marcador
CALIB_LANE = 2  # las notas de la calibración bajan por el carril amarillo (el del centro)
MENU_HINT = N_("Strum: mover · Verde / +: elegir · Rojo / −: volver")
LONG_HINT = N_("Strum: mover · Verde / +: elegir · Rojo / −: volver · Amarillo / Azul: pasar página")
POSITIONS = TrDict({"left": N_("Izquierda"), "center": N_("Centro"), "right": N_("Derecha")})
MENU_REPEAT_S = (0.35, 0.08, 0.035)  # strum mantenido en un menú: espera, repetición y, pasados 2 s, más rápido
SIDES = TrDict({"left": N_("Izquierda"), "right": N_("Derecha")})
AIMP_CHECK_S = 0.3  # cada cuánto se mira qué canción tiene AIMP
OWN_SEEK_S = 0.6  # los saltos que hace el propio juego en AIMP (reiniciar) no cuentan como saltos del usuario
SONG_COMMANDS = ("next", "prev", "random")  # botones 1, 2 y Home del Wiimote
PHRASE_FLASH_S = 0.6  # la barra de star power se enciende al completar una frase
USAGE = N_("Music Hero: juega con la guitarra sobre la canción que suena.\n\n"
           "    play                      el selector de canciones\n"
           "    play \"<canción o carpeta de chart>\" [--difficulty hard]\n"
           "    play --hidden             oculto: Ctrl+Alt+H lo muestra; si suena AIMP, lo sigue")
WELCOME = N_("Para jugar, Music Hero necesita tu música: elige la carpeta donde la tienes y hará las charts "
             "(notas y letra) en segundo plano, primero la canción que elijas.")


def blank_chart() -> Chart:
    """Sin ninguna canción con chart todavía (recién instalado): una vacía, sin notas, mientras se hacen."""
    return Chart("Music Hero", "", Path(""), "", 0, [], {"expert": []}, CHARTS_DIR)


def blank_player(volume: float) -> Player:
    return Player((np.zeros((4800, 2), np.float32), 48000), 0.0, 0.0, volume)


class Session(QObject):
    def __init__(self, chart: Chart, cfg: Config, difficulty: str | None, inputs: Inputs, view: QQuickView,
                 records: Records | None = None, aimp: Aimp | None = None, engine: EngineClient | None = None):
        super().__init__()
        self.cfg, self.inputs, self.view = cfg, inputs, view
        self.records = records or Records()
        self.player: Player | AimpPlayer | None = None
        self.aimp = aimp or Aimp()
        self.follow = False  # el juego sigue a AIMP
        self.aimp_file: str | None = None  # canción de AIMP ya atendida
        self.aimp_title = ""
        self.waiting = ""  # siguiendo a AIMP, su canción no tiene chart: el aviso (y no se juega)
        self.aimp_check = 0.0
        self.own_seek_until = 0.0
        self.engine = engine or EngineClient()  # genera las charts en otro proceso (engine.py)
        self.installer = installer.EngineInstaller()  # la app instalada lo instala la primera vez que hace falta
        self.install_asked = False  # ya se ofreció instalarlo en esta sesión (no se insiste solo)
        self.install_seen = ""  # último estado del instalador ya atendido
        self.wanted: str | None = None  # canción sin chart que ha elegido el usuario: se juega en cuanto esté
        self.watcher = MusicWatcher()  # recorre las carpetas de música en un hilo
        self.music: list[str] = []  # todo el audio de las carpetas
        self.missing: list[str] = []  # el que aún no tiene chart
        self.dialog_open = False  # diálogo de Windows abierto (elegir carpeta): el juego no se pone encima
        self._by_path: dict[str, Entry] | None = None
        self.synced = False  # retardo de AIMP ya medido desde que se le sigue
        self.sync_thread: threading.Thread | None = None
        self.sync_result: tuple[AimpPlayer, float | None] | None = None  # lo deja el hilo de la medida
        self.sync_retry_at = 0.0
        self._tree: dict[str, dict[str, list[Entry]]] | None = None
        self.held = [False] * 5
        self.flash_t = [0.0] * 5
        self.miss_t = 0.0
        self.miss_lane_t = [0.0] * 5
        self.resume_at: float | None = None
        self.menus: list[Menu] = []
        self.calib: Player | None = None
        self.calib_strums: list[float] = []
        self.calib_hits: set[int] = set()  # notas de la calibración ya rasgueadas
        self.results = ""
        self.toast_text, self.toast_until = "", 0.0
        self.guitar_connected: bool | None = None
        self.text_mode = False  # el teclado escribe (buscador abierto)
        self.capturing: str | None = None  # acción esperando su tecla nueva (Ajustes → Teclas)
        self.mouse_on = False  # la ventana recibe el ratón (hay un menú abierto)
        self.tray: QSystemTrayIcon | None = None  # icono junto al reloj (main)
        self.right_click: win32.RightClick | None = None  # clic derecho en la autopista: el menú (main)
        self.strum_hold: tuple[int, float, float] | None = None  # strum mantenido en un menú: (dirección, desde, siguiente)
        self.message = "; ".join(inputs.errors)
        self.autoplay = False
        self.partial = False  # la partida no cuenta para récords (automático o empezada a mitad)
        self.record_toast = False  # ya se avisó de que se ha superado el récord en esta partida
        self.load_song(chart, difficulty)
        if cfg.library_dirs:
            self.watcher.set_dirs(cfg.library_dirs)

    def load_song(self, chart: Chart, difficulty: str | None = None, player: AimpPlayer | None = None) -> None:
        """Pone esta canción (al empezar, desde el selector o la que suena en AIMP, con player): su dificultad es
        la pedida, la última elegida en ella o la de por defecto."""
        self.stop_calibration()
        if not chart.audio_sha256:
            player = blank_player(self.cfg.volume)
        player = player or Player(chart.audio_file, self.cfg.audio_offset_ms, LEAD_IN_MS, self.cfg.volume)
        if self.player:
            self.player.close()
        self.chart, self.player = chart, player
        self.lyrics = Lyrics.load(chart.folder, chart.audio_sha256)
        d = difficulty or self.records.difficulty(chart.audio_sha256) or self.cfg.difficulty
        self.difficulty = d if d in chart.difficulties else next(iter(chart.difficulties))
        self.beats = chart.beats
        self.beat_times = [b[0] for b in self.beats]
        # frases de star power: las de la chart (v2, de la humana) o, si no trae, las de la heurística; las de la
        # dificultad más alta valen para las que no tengan (muchas charts solo las marcan en Experto)
        hardest = next(d for d in DIFFS if d in chart.difficulties)
        self.phrases = (next((chart.star_power[d] for d in DIFFS if chart.star_power.get(d)), None)
                        or starpower.phrases(chart.difficulties[hardest], chart.beats))
        self.menus.clear()
        self.results, self.resume_at = "", None
        self.flash_t, self.miss_lane_t, self.miss_t = [0.0] * 5, [0.0] * 5, 0.0
        if chart.audio_sha256:
            self.records.set_last(chart.audio_sha256)
        self.new_game()
        if self.player.lead_in:  # el propio; AIMP ya está sonando (o en pausa, como lo haya dejado el usuario)
            self.player.play()

    # ---------- partida ----------

    def new_game(self) -> None:
        notes = self.chart.difficulties[self.difficulty]
        self.game = Game(notes, phrases=self.chart.star_power.get(self.difficulty) or self.phrases, beats=self.beat_times)
        self.game.held |= {i for i, h in enumerate(self.held) if h}
        self.phrase_t = self.star_t = 0.0  # cuándo se completó la última frase y cuándo se activó
        self.star_hint = False  # ya se avisó de que se puede activar
        self.times = [n.time_ms for n in notes]
        self.max_sustain = max((n.sustain_ms for n in notes), default=0)
        self.partial = self.autoplay
        self.record_toast = False
        best = self.records.best(self.chart.audio_sha256, self.difficulty)
        self.best_score = best.score if best else 0

    def restart(self) -> None:
        self.menus.clear()
        self.player.pause()
        self.own_seek_until = time.perf_counter() + OWN_SEEK_S
        self.player.seek(-LEAD_IN_MS if self.player.lead_in else 0)
        self.new_game()
        self.results, self.resume_at = "", None
        if self.player.lead_in:
            self.player.play()
        else:  # AIMP: sin silencio antes del principio, cuenta atrás con la canción parada
            self.resume_at = time.perf_counter() + RESUME_MS / 1000

    def pause(self) -> None:
        self.player.pause()
        self.resume_at = None
        if not self.menus:
            self.menus.append(self.pause_menu())

    def resume(self) -> None:
        self.menus.clear()
        if not self.player.playing and self.resume_at is None:
            self.resume_at = time.perf_counter() + RESUME_MS / 1000

    def set_difficulty(self, d: str) -> None:
        if d == self.difficulty or d not in self.chart.difficulties:
            return
        self.difficulty = d
        self.records.set_difficulty(self.chart.audio_sha256, d, self.chart.title, self.chart.artist)
        self.toast(t("Dificultad: {name}", name=DIFF_NAMES[d]))
        if self.results:
            return  # se juega al elegir "Otra vez"
        pos = self.player.position_ms()
        self.new_game()
        if pos > 0:
            self.game.skip_to(pos + (SWITCH_AHEAD_MS if self.player.playing else 0))
            self.partial = True  # empezada a mitad: no cuenta para récords

    def cycle_difficulty(self) -> None:
        """Tab / −: a la siguiente más fácil, y de Fácil vuelve a Experto."""
        avail = [d for d in DIFFS if d in self.chart.difficulties]
        self.set_difficulty(avail[(avail.index(self.difficulty) + 1) % len(avail)])

    def toggle_visible(self) -> None:
        if self.view.isVisible():
            if not self.follow:  # siguiendo a AIMP, la música sigue aunque no se vea el juego
                self.pause()
            self.inputs.set_game_keys(False)
            self.view.hide()
            if self.right_click:
                self.right_click.rect = None
        else:
            if self.follow and not self.waiting:
                self.resync()  # oculto no se pinta ni se juzga: se sigue desde donde va AIMP
            elif self.aimp.connected() and self.aimp.state() == PLAYING:
                self.follow_aimp()  # Ctrl+Alt+H con algo sonando en AIMP: a seguirlo
            self.view.show()
            win32.make_click_through(int(self.view.winId()))
            self.mouse_on = False  # recién mostrado deja pasar los clics; el próximo fotograma lo ajusta al menú
            self.inputs.set_game_keys(True)

    def toast(self, text: str, seconds: float = TOAST_S) -> None:
        self.toast_text, self.toast_until = text, time.perf_counter() + seconds

    # ---------- AIMP ----------

    def follow_aimp(self) -> bool:
        """Empieza a seguir a AIMP (si ya lo seguía, nada). False si AIMP no tiene canción."""
        if self.follow:
            return True
        if not self.aimp.connected() or self.aimp.track() is None:
            return False
        self.follow, self.aimp_file, self.aimp_check = True, None, 0.0
        self.synced, self.sync_retry_at = False, 0.0
        self.menus.clear()
        self.resume_at = None
        self.watch_aimp(time.perf_counter())
        return True

    def resync(self) -> None:
        """Partida nueva desde donde va la canción (las notas de antes no cuentan, ni la partida para récords)."""
        pos = self.player.position_ms()
        self.new_game()
        if pos > 0:
            self.game.skip_to(pos + SWITCH_AHEAD_MS)
            self.partial = True

    def follow_from_menu(self) -> None:
        if not self.follow_aimp():
            self.toast(t("AIMP no tiene ninguna canción puesta"))
        elif not self.waiting:
            self.player.play()

    def stop_following(self) -> None:
        if self.follow and self.aimp.state() == PLAYING:
            self.aimp.command(CMD_PAUSE)  # PAUSE alterna: solo si está sonando
        self.follow, self.aimp_file, self.waiting = False, None, ""

    def chart_for(self, audio: str) -> Chart | None:
        """Chart de un archivo de audio: por su ruta en el índice de la biblioteca o, si no está, por su hash."""
        key = lambda p: os.path.normcase(os.path.abspath(p))  # noqa: E731
        if self._by_path is None:
            self._by_path = {key(e.audio): e for e in scan()}
        e = self._by_path.get(key(audio))
        if e is not None:
            folder, path = Path(e.folder), Path(e.audio)
        else:
            path = Path(audio)
            folder = find_chart(path) if path.is_file() else None
            if folder is None:
                return None
        chart = Chart.load(folder)
        chart.audio_file = path
        return chart

    def watch_aimp(self, now: float) -> None:
        """Cada AIMP_CHECK_S: la generación en segundo plano y, siguiendo a AIMP, si ha cambiado de canción."""
        if now < self.aimp_check:
            return
        self.aimp_check = now + AIMP_CHECK_S
        if not self.follow:
            return
        if not self.aimp.connected():
            self.stop_following()
            self.load_song(self.chart)
            self.pause()
            self.toast(t("AIMP se ha cerrado: vuelve el reproductor propio"), 5)
            return
        track = self.aimp.track()
        if track is not None and track.file != self.aimp_file:
            self.aimp_file = track.file
            self.open_aimp_track(track)
        self.check_sync(now)

    def check_sync(self, now: float) -> None:
        """Mide en segundo plano cuánto tarda en oírse AIMP (loopback.py) y ajusta el reloj con lo medido."""
        if self.sync_result is not None:
            player, lag = self.sync_result
            self.sync_result, self.sync_thread = None, None
            if lag is None:
                self.sync_retry_at = now + 20  # otro sonido a la vez, un ecualizador...: más tarde
            elif player is self.player:
                self.synced = True
                self.cfg.aimp_offset_ms = round(lag)
                self.cfg.save()
                self.apply_offsets()
        player = self.player
        if (self.synced or self.sync_thread is not None or now < self.sync_retry_at
                or not isinstance(player, AimpPlayer) or not player.playing or player.position_ms() < 1000):
            return

        def run() -> None:
            raw = lambda t: player.position_ms(t) + player.offset_ms  # noqa: E731 - la posición de AIMP, tal cual
            try:
                lag = loopback.measure(player.track.file, raw)
            except Exception as err:  # noqa: BLE001 - sin loopback se sigue con el retardo guardado
                print(t("medida del retardo de AIMP: {err}", err=err))
                lag = None
            print(t("retardo de AIMP: {lag:+.0f} ms", lag=lag) if lag is not None
                  else t("retardo de AIMP: no se pudo medir"))
            self.sync_result = (player, lag)
        self.sync_thread = threading.Thread(target=run, daemon=True, name="sincronía")
        self.sync_thread.start()

    def open_aimp_track(self, track: Track) -> None:
        self.aimp_title = track.title or Path(track.file).stem
        try:
            chart = self.chart_for(track.file)
        except Exception as err:  # noqa: BLE001 - una chart rota no tira el juego
            print(t("chart de {file}: {err}", file=track.file, err=err))
            chart = None
        if chart is None:
            generating = self.chart_state(track.file) in ("en cola", "generando")
            self.waiting = (t("«{title}» no tiene chart todavía (generándola…)", title=self.aimp_title) if generating
                            else t("«{title}» no tiene chart todavía: + / Espacio para generarla", title=self.aimp_title))
            self.player.close()  # sin chart no se juega, pero la pausa y el seguir siguen siendo los de AIMP
            self.player = AimpPlayer(self.aimp, track, self.aimp_offset())
            return
        self.waiting = ""
        player = AimpPlayer(self.aimp, track, self.aimp_offset())
        self.load_song(chart, player=player)
        pos = player.position_ms()
        if pos > 1500:  # empezada a mitad: las notas pasadas no cuentan, y la partida tampoco para récords
            self.game.skip_to(pos + SWITCH_AHEAD_MS)
            self.partial = True
        self.toast(f"AIMP: {chart.artist} – {chart.title} · {DIFF_NAMES[self.difficulty]}")

    def generate_current(self) -> None:
        """Genera la chart de la canción de AIMP (delante de la cola del motor: ~1 min con GPU)."""
        if not self.aimp_file or not self.request_chart(self.aimp_file, self.aimp_title):
            return
        self.waiting = t("«{title}» no tiene chart todavía (generándola…)", title=self.aimp_title)
        self.resume()

    # ---------- biblioteca y motor ----------

    @property
    def blank(self) -> bool:
        """Todavía sin ninguna canción (recién instalado): no hay nada que jugar."""
        return not self.chart.audio_sha256

    def tick_library(self, now: float) -> None:
        """Cada fotograma (y oculto, cada 50 ms): lo que ha encontrado el vigilante de carpetas y lo que dice el
        motor. El motor se pausa mientras se juega."""
        music = self.watcher.take()
        if music is not None:
            self.music = music
            self.update_missing()
        if self.installer.state != self.install_seen:
            self.install_seen = self.installer.state
            if self.installer.state == "done":
                self.toast(t("Motor de generación instalado: empiezan las charts"), 5)
                self.update_missing()
                if self.wanted:
                    self.engine.add([self.wanted], front=True)
            elif self.installer.state == "error":
                self.toast(t("No se pudo instalar el motor: {err}", err=self.installer.error[:150]), 8)
        for ev in self.engine.poll():
            kind = ev.get("event")
            if kind == "done":
                self._by_path = self._tree = None  # índice nuevo: ya está la chart
                self.missing = [m for m in self.missing if norm(m) != norm(ev["file"])]
                self.chart_ready(ev["file"])
            elif kind == "error" and ev.get("file"):
                self.chart_failed(ev["file"], ev.get("message", ""))
        st = self.engine.state
        if self.wanted and st.current and norm(st.current) == norm(self.wanted):
            self.toast(t("Generando la chart de «{name}»: {pct} %", name=Path(self.wanted).stem,
                         pct=round(st.done * 100)), 1.0)
        playing = (self.view.isVisible() and self.player.playing and not self.menus and not self.waiting
                   and not self.calib and not self.blank)
        self.engine.set_paused(playing)

    def update_missing(self) -> None:
        """Lo que no tiene chart en las carpetas; con «Generar en segundo plano», a la cola del motor."""
        self.missing = without_chart(self.music, scan())
        self._tree = None
        self.refresh_welcome()
        if self.cfg.background and self.missing:
            if installer.needed():
                self.offer_install()
            else:
                self.engine.add(self.missing)

    def refresh_welcome(self) -> None:
        """La bienvenida abierta se rehace (con «Elegir canción» si ya hay canciones), en la misma opción."""
        for i, m in enumerate(self.menus):
            if m.key == "welcome" and not m.editing:
                label = m.options[m.sel].label if m.options else ""
                new = self.welcome_menu()
                new.sel = next((j for j, o in enumerate(new.options) if o.label == label), 0)
                self.menus[i] = new

    def chart_state(self, audio: str) -> str:
        """Estado de una canción sin chart: «generando», «en cola», «falló» o «sin chart» (para enseñarlo, t())."""
        st = self.engine.state
        if st.current and norm(st.current) == norm(audio):
            return N_("generando")
        pending, failed = self.engine.snapshot()
        key = os.path.normcase(audio)
        return N_("falló") if key in failed else N_("en cola") if key in pending else N_("sin chart")

    def request_chart(self, audio: str, title: str) -> bool:
        """El usuario quiere esta canción: delante de la cola del motor (aunque hubiera fallado antes)."""
        if installer.needed():
            self.wanted = audio  # se hará en cuanto esté el motor
            self.offer_install(force=True)
            return False
        if not self.engine.available():
            self.toast(t("No se puede generar la chart: no se encuentra el motor (¿falta uv?)"), 6)
            return False
        self.engine.add([audio], front=True)
        self.wanted = audio
        self.toast(t("Generando la chart de «{title}»… (en torno a 1 min con GPU)", title=title), 5)
        return True

    def chart_ready(self, audio: str) -> None:
        if self.wanted and norm(self.wanted) == norm(audio):
            self.wanted = None
            e = next((e for e in scan() if norm(e.audio) == norm(audio)), None)
            if e is not None:
                self._load_entry(e)
            return
        if self.follow and self.waiting and self.aimp_file and norm(self.aimp_file) == norm(audio):
            track = self.aimp.track()
            if track is not None and norm(track.file) == norm(audio):
                self.open_aimp_track(track)
            return
        if self.blank and (not self.menus or self.menus[-1].key == "welcome"):  # la primera de todas
            self.toast(t("¡Ya hay canciones para jugar!"), 5)
            self.open_selector()

    def chart_failed(self, audio: str, message: str) -> None:
        name = Path(audio).stem
        if self.wanted and norm(self.wanted) == norm(audio):
            self.wanted = None
            self.toast(t("No se pudo generar la chart de «{name}»: {err}", name=name, err=message[:120]), 8)
        if self.follow and self.waiting and self.aimp_file and norm(self.aimp_file) == norm(audio):
            self.waiting = t("«{name}» no tiene chart: falló al generarla", name=name)

    def offer_install(self, force: bool = False) -> None:
        """La app instalada aún sin motor: se ofrece instalarlo (una vez por sesión, salvo si lo pide el usuario)."""
        if self.installer.state == "running":
            self.toast(t("Instalando el motor: {step}", step=self.installer.step), 4)
            return
        if self.install_asked and not force:
            return
        self.install_asked = True
        drv = installer.driver_version()
        gpu = drv is not None and drv >= installer.MIN_DRIVER
        size = installer.SIZE_GB["cuda" if gpu else "cpu"]

        def go() -> None:
            self.installer.start()
            self.menu_back()
            self.toast(t("Instalando el motor de generación: puedes seguir jugando mientras"), 5)
        body = t("Para hacer las charts, Music Hero necesita su motor de generación (separar instrumentos, ritmo, "
                 "notas y letra). Se descarga una sola vez: unos {size} GB a %LOCALAPPDATA%\\MusicHero.", size=size)
        body += "<br>" + (t("Tienes una tarjeta NVIDIA: cada canción tardará un minuto más o menos.") if gpu else
                          t("Sin tarjeta NVIDIA (o con el driver antiguo) cada canción tardará varios minutos.")
                          + (" " + t("Con el driver de NVIDIA al día iría mucho más rápido.") if drv is not None else ""))
        if self.menus and self.menus[-1].key == "install":
            return
        self.menus.append(Menu(t("Instalar el motor"), [Option(t("Instalar ahora"), go),
                                                        Option(t("Más tarde"), self.menu_back)],
                               body=body, key="install"))

    def library_line(self) -> str:
        """Una línea con lo que está haciendo el motor (Ajustes → Biblioteca, el icono de la bandeja)."""
        if self.installer.state == "running":
            return t("instalando el motor ({pct} %): {step}", pct=round(self.installer.done * 100),
                     step=self.installer.step)
        if installer.needed():
            return t("falta instalar el motor de generación")
        st = self.engine.state
        paused = " · " + t("en pausa mientras juegas") if st.paused else ""
        if st.current:
            line = t("generando «{name}» ({pct} %)", name=Path(st.current).stem, pct=round(st.done * 100))
            if st.pending > 1:
                line += " · " + t("{n} más en cola", n=st.pending - 1)
            return line + paused
        if st.pending:
            return t("{n} en cola", n=st.pending) + paused
        if self.missing and not self.cfg.background:
            return t("{n} sin chart (generar en segundo plano: no)", n=len(self.missing))
        return t("al día") if self.cfg.library_dirs else t("sin carpetas de música (Ajustes → Biblioteca)")

    def library_menu(self) -> Menu:
        cfg = self.cfg

        def set_background(v: bool) -> None:
            cfg.background = v
            cfg.save()
            if v:
                self.update_missing()
            else:  # fuera de la cola lo de las carpetas (lo que haya pedido el usuario, no)
                self.engine.remove([m for m in self.missing if not (self.wanted and norm(m) == norm(self.wanted))])

        opts = [Option(t("Añadir carpeta"), lambda: QTimer.singleShot(0, self.add_library_dir))]
        opts += [Option(Path(d).name or d, lambda d=d: self.menus.append(self.folder_menu(d)), value=t("carpeta"))
                 for d in cfg.library_dirs]
        opts.append(Option(t("Generar en segundo plano"), value=lambda: yes_no(cfg.background), sep=True,
                           change=cycler([False, True], lambda: cfg.background, set_background)))
        if installer.needed():
            opts.append(Option(t("Instalar el motor"), lambda: self.offer_install(force=True)))
        opts.append(Option(t("Reintentar las que fallaron"), self.engine.retry))
        opts.append(Option(t("Volver"), self.menu_back, sep=True))
        return Menu(t("Biblioteca"), opts, body=self.library_body, key="library")

    def library_body(self) -> str:
        st = self.engine.state
        total, missing = len(self.music), len(self.missing)
        lines = [t("{dirs} carpetas · {total} canciones · {done} con chart", dirs=len(self.cfg.library_dirs),
                   total=total, done=total - missing)
                 if self.cfg.library_dirs else t("Añade la carpeta donde tienes tu música.")]
        lines.append(t("Ahora: {line}", line=self.library_line()))
        if st.failed:
            lines.append(t("{n} no se pudieron generar (detalles en {log})", n=st.failed, log=self.engine.log.name))
        if st.device == "cpu":
            lines.append(t("Sin tarjeta NVIDIA: cada canción tarda varios minutos"))
        if st.error:
            lines.append(st.error)
        if self.installer.state == "error":
            lines.append(t("La instalación del motor falló: {err} (se puede repetir)", err=self.installer.error[:200]))
        return "<br>".join(lines)

    def folder_menu(self, folder: str) -> Menu:
        def drop() -> None:
            self.cfg.library_dirs = [d for d in self.cfg.library_dirs if d != folder]
            self.cfg.save()
            self.engine.remove([m for m in self.music if in_dirs(m, [folder])])
            self.watcher.set_dirs(self.cfg.library_dirs)
            self.menus.pop()  # este
            self.menus.pop()  # y la biblioteca, que se vuelve a abrir con las carpetas de ahora
            self.menus.append(self.library_menu())
        return Menu(Path(folder).name or folder, [Option(t("Quitar de la biblioteca"), drop),
                                                 Option(t("Volver"), self.menu_back)],
                    body=folder + "<br>" + t("Al quitarla no se borra nada: las charts hechas se quedan, pero deja "
                                             "de buscar canciones nuevas ahí."))

    def add_library_dir(self) -> None:
        """Diálogo de Windows para elegir la carpeta. Mientras está abierto, el juego se aparta (se oculta y suelta
        el teclado) para que se pueda usar."""
        self.dialog_open = True
        self.inputs.set_game_keys(False)
        self.view.hide()
        start = self.cfg.library_dirs[-1] if self.cfg.library_dirs else str(Path.home() / "Music")
        try:
            folder = QFileDialog.getExistingDirectory(None, t("Carpeta de tu música"), start)
        finally:
            self.dialog_open = False
            self.view.show()
            win32.make_click_through(int(self.view.winId()))
            self.mouse_on = False
            self.inputs.set_game_keys(True)
        if not folder:
            return
        folder = str(Path(folder))
        if any(norm(folder) == norm(d) or in_dirs(folder, [d]) for d in self.cfg.library_dirs):
            self.toast(t("Esa carpeta ya está en la biblioteca"))
            return
        self.cfg.library_dirs = [d for d in self.cfg.library_dirs if not in_dirs(d, [folder])] + [folder]
        self.cfg.save()
        self.watcher.set_dirs(self.cfg.library_dirs)
        self.toast(t("Buscando canciones en {folder}…", folder=folder), 4)
        if self.menus and self.menus[-1].key == "library":
            self.menus[-1] = self.library_menu()

    def pairing_menu(self) -> Menu:
        """Emparejar la guitarra (el Wiimote) con Windows: busca en un hilo y enseña los avisos."""
        stop, said = threading.Event(), []
        threading.Thread(target=pairing.pair, args=(said.append, stop), daemon=True, name="emparejar").start()

        def leave() -> None:
            stop.set()
            self.menu_back()
        return Menu(t("Emparejar la guitarra"), [Option(t("Volver"), leave)],
                    body=lambda: (t("Con la guitarra enchufada al Wiimote, pulsa el botón rojo de sync del Wiimote "
                                    "(bajo la tapa de las pilas).") + "<br><br>" + (said[-1] if said else "")))

    def welcome_menu(self) -> Menu:
        """Sin canciones todavía. «Elegir canción», cuando ya hay alguna en las carpetas (aunque sin chart: al
        elegirla se hace la primera); refresh_welcome() la añade al encontrarlas."""
        choose = [Option(t("Elegir canción"), self.open_selector)] if self.tree() else []
        return Menu("Music Hero", [
            Option(t("Añadir la carpeta de tu música"), lambda: self.menus.append(self.library_menu())),
            *choose,
            Option(t("Emparejar la guitarra de Wii"), lambda: self.menus.append(self.pairing_menu())),
            Option(t("Ajustes"), lambda: self.menus.append(self.settings_menu()), sep=True),
            sep_above(self.leave_option()),
        ], body=lambda: t(WELCOME) + ("<br><br>" + t("Biblioteca: {line}", line=self.library_line())
                                      if self.cfg.library_dirs else ""), key="welcome")

    # ---------- menús ----------

    def difficulty_option(self) -> Option:
        avail = [d for d in reversed(DIFFS) if d in self.chart.difficulties]  # de Fácil a Experto: arriba sube
        return Option(t("Dificultad"), value=lambda: DIFF_NAMES[self.difficulty],
                      change=cycler(avail, lambda: self.difficulty, self.set_difficulty))

    def set_autoplay(self, on: bool) -> None:
        self.autoplay = on
        if on:
            self.partial = True  # las partidas con el modo automático no cuentan para récords

    def autoplay_option(self) -> Option:
        return Option(t("Modo automático"), value=lambda: yes_no(self.autoplay),
                      change=cycler([False, True], lambda: self.autoplay, self.set_autoplay))

    def record_line(self) -> str:
        sha = self.chart.audio_sha256
        best = self.records.best(sha, self.difficulty)
        name = DIFF_NAMES[self.difficulty]
        if best is None:
            return t("Sin récord en {name} todavía", name=name)
        st = self.records.stats(sha, self.difficulty)
        line = t("Récord en {name}: <b>{score}</b> · {acc:.0%} · racha {streak}", name=name,
                 score=fmt_int(best.score), acc=best.accuracy, streak=best.best_streak)
        if best.full_combo:
            line += " · " + t("sin fallos")
        return line + "<br>" + t("{n} partidas · el {date}", n=st.get("plays", 0), date=fmt_date(best.date))

    # ---------- selector de canciones ----------

    def tree(self) -> dict[str, dict[str, list[Entry]]]:
        """Las canciones con chart y, de las carpetas de música, las que aún no la tienen."""
        if self._tree is None:
            self._tree = group(scan() + pending_entries(self.missing))
        return self._tree

    def song_value(self, e: Entry) -> str:
        """A la derecha de cada canción: su récord (en la dificultad que se le pondría) y la duración; si aún no
        tiene chart, en qué está."""
        if not e.folder:
            state = self.chart_state(e.audio)
            if state == "generando":
                return t("generando {pct} %", pct=round(self.engine.state.done * 100))
            return t(state)
        d = self.records.difficulty(e.sha) or self.cfg.difficulty
        best = self.records.best(e.sha, d)
        length = f"{e.duration_ms // 60000}:{e.duration_ms // 1000 % 60:02d}"
        return f"{fmt_int(best.score)} · {length}" if best else length

    def open_selector(self) -> None:
        """Artistas -> álbumes -> canciones, abierto ya en la canción que suena (rojo / − va subiendo)."""
        self.pause()
        tree = self.tree()
        if not tree:
            if self.blank and self.menus and self.menus[-1].key == "pause":  # pause() la acaba de abrir
                self.menus[-1] = self.welcome_menu()
            self.toast(t("Todavía no hay canciones: añade la carpeta de tu música") if not self.music
                       else t("Buscando canciones…"))
            return
        here = next(((a, al, i) for a, albums in tree.items() for al, songs in albums.items()
                     for i, e in enumerate(songs) if e.sha == self.chart.audio_sha256), None)
        total = sum(len(s) for albums in tree.values() for s in albums.values())
        body = t("{n} canciones de {artists} artistas", n=total, artists=len(tree))
        if self.missing:
            body += " " + t("({n} aún sin chart: elige una y se hace la primera)", n=len(self.missing))
        root = Menu(t("Canciones"), [Option(t("Buscar"), self.open_search), Option(t("Al azar"), self.play_random)] + [
            Option(a, lambda a=a: self.open_artist(a), value=str(sum(len(s) for s in tree[a].values())))
            for a in tree], body=body)
        self.menus.append(root)
        if here:
            artist, album, i = here
            root.sel = 2 + list(tree).index(artist)
            self.open_artist(artist, album, i)

    def open_artist(self, artist: str, album: str | None = None, song: int = 0) -> None:
        albums = self.tree()[artist]
        if len(albums) == 1:
            self.open_album(artist, next(iter(albums)), song)
            return
        menu = Menu(artist, [Option(al, lambda al=al: self.open_album(artist, al), value=str(len(albums[al])))
                             for al in albums], body=t("{n} álbumes", n=len(albums)))
        self.menus.append(menu)
        if album in albums:
            menu.sel = list(albums).index(album)
            self.open_album(artist, album, song)

    def open_album(self, artist: str, album: str, song: int = 0) -> None:
        songs = self.tree()[artist][album]
        menu = Menu(album, [Option(e.title, lambda e=e: self.choose(e), value=self.song_value(e)) for e in songs],
                    body=artist + " · " + t("{n} canciones", n=len(songs)))
        menu.sel = min(song, len(songs) - 1)
        self.menus.append(menu)

    def open_search(self) -> None:
        """Buscador por título, artista o álbum (teclado directo, o letra a letra con la guitarra)."""
        self.pause()
        entries = [e for albums in self.tree().values() for s in albums.values() for e in s]

        def results(query: str) -> list[Option]:
            return [Option(e.title, lambda e=e: self.choose(e), value=e.group_artist)
                    for e in search(entries, query)]
        self.menus.append(SearchMenu(t("Buscar canción"), results))

    def choose(self, e: Entry) -> None:
        if not e.folder:  # aún sin chart: delante de la cola, y se juega en cuanto esté
            self.request_chart(e.audio, e.title)
            return
        if e.sha == self.chart.audio_sha256:
            self.restart()
            return
        self.toast(t("Cargando {title}…", title=e.title), 10)
        QTimer.singleShot(30, lambda: self._load_entry(e))  # deja pintar el aviso antes de leer el audio

    def _load_entry(self, e: Entry) -> None:
        try:
            chart = Chart.load(Path(e.folder))
            chart.audio_file = Path(e.audio)
            self.stop_following()  # una canción elegida aquí suena en el reproductor propio
            self.load_song(chart)
            if not self.view.isVisible():
                self.pause()  # cambiada con el juego oculto (botones del Wiimote): espera a que se muestre
        except Exception as err:  # noqa: BLE001 - una canción rota no tira el juego
            self.toast(t("No se pudo abrir {title}: {err}", title=e.title, err=err), 6)
            return
        self.toast(f"{chart.artist} – {chart.title} · {DIFF_NAMES[self.difficulty]}")

    def play_random(self) -> None:
        songs = [e for albums in self.tree().values() for s in albums.values() for e in s
                 if e.folder and e.sha != self.chart.audio_sha256]
        if songs:
            self.choose(random.choice(songs))

    def pause_menu(self) -> Menu:
        extra = []
        if self.waiting and self.aimp_file and self.chart_state(self.aimp_file) not in ("en cola", "generando"):
            extra.append(Option(t("Generar la chart"), self.generate_current))
        if not self.follow and self.aimp.connected() and self.aimp.track() is not None:
            extra.append(Option(t("Seguir a AIMP"), self.follow_from_menu))
        return Menu(t("Pausa"), [
            Option(t("Continuar"), self.resume),
            *extra,
            Option(t("Cambiar canción"), self.open_selector, sep=True),
            Option(t("Canción al azar"), self.play_random),
            Option(t("Buscar canción"), self.open_search),
            sep_above(self.difficulty_option()),
            self.autoplay_option(),
            Option(t("Reiniciar"), self.restart),
            Option(t("Ajustes"), lambda: self.menus.append(self.settings_menu()), sep=True),
            sep_above(self.leave_option()),
        ], body=self.pause_body, on_back=self.resume, key="pause")

    def leave_option(self) -> Option:
        """Con el icono junto al reloj, ocultar (se sale desde el icono); sin él, salir."""
        return Option(t("Ocultar"), self.toggle_visible) if self.tray else Option(t("Salir"), QGuiApplication.quit)

    def pause_body(self) -> str:
        if self.waiting:
            return f"AIMP: {self.waiting}"
        if self.blank:
            return t("Todavía no hay canciones. Biblioteca: {line}", line=self.library_line())
        source = "AIMP · " if self.follow else ""
        return f"{source}{self.chart.artist} – {self.chart.title}<br>{self.record_line()}"

    def results_menu(self) -> Menu:
        return Menu(t("Fin de la canción"), [
            Option(t("Otra vez"), self.restart),
            Option(t("Otra canción"), self.open_selector),
            Option(t("Canción al azar"), self.play_random),
            Option(t("Buscar canción"), self.open_search),
            sep_above(self.difficulty_option()),
            self.autoplay_option(),
            Option(t("Ajustes"), lambda: self.menus.append(self.settings_menu()), sep=True),
            sep_above(self.leave_option()),
        ], body=lambda: self.results, key="results")

    def num(self, name: str, step: float, lo: float, hi: float, after=None):
        """change() para un ajuste numérico de la config: con paso y límites, y se guarda solo."""
        def set_(v: float) -> None:
            setattr(self.cfg, name, v)
            if after:
                after()
            self.cfg.save()
        return stepper(lambda: getattr(self.cfg, name), set_, step, lo, hi)

    def settings_menu(self) -> Menu:
        """Por grupos: lo de fuera del juego (biblioteca, mando), los submenús de ajustes y, en la app
        instalada, abrirla al iniciar Windows."""
        def sub(make):
            return lambda: self.menus.append(make())

        cfg = self.cfg

        def set_lang(v: str) -> None:  # el menú se rehace en el idioma nuevo, en la misma opción y editándola
            cfg.language = v
            cfg.save()
            set_language(v)
            old = self.menus[-1]
            new = self.settings_menu()
            new.sel, new.editing = old.sel, old.editing
            self.menus[-1] = new

        opts = [
            Option(t("Biblioteca"), sub(self.library_menu), value=self.library_short),
            Option(t("Guitarra y teclas"), sub(self.controls_menu),
                   value=lambda: t("conectada") if self.inputs.guitar.connected else ""),
            Option(t("Juego"), sub(self.game_settings_menu), sep=True),
            Option(t("Pantalla"), sub(self.display_menu)),
            Option(t("Sonido y retardo"), sub(self.sound_menu)),
            Option(t("Idioma"), value=lambda: t("Automático") if cfg.language == "auto" else LANGS[cfg.language],
                   change=cycler(list(LANGS), lambda: cfg.language, set_lang)),
        ]
        if FROZEN:  # la de desarrollo se lanza con uv: no tiene un .exe que poner al iniciar Windows
            on = [win32.autostart()]

            def set_autostart(v: bool) -> None:
                win32.set_autostart(v, f'"{sys.executable}" --hidden')
                on[0] = win32.autostart()
            opts.append(Option(t("Abrir al iniciar Windows"), value=lambda: yes_no(on[0]), sep=True,
                               change=cycler([False, True], lambda: on[0], set_autostart)))
        opts.append(Option(t("Volver"), self.menu_back, sep=True))
        return Menu(t("Ajustes"), opts, body=t("Elige una opción para cambiarla con el strum; se guarda sola."))

    def game_settings_menu(self) -> Menu:
        cfg, num = self.cfg, self.num
        return Menu(t("Juego"), [
            Option(t("Dificultad por defecto"), value=lambda: DIFF_NAMES.get(cfg.difficulty, cfg.difficulty),
                   change=cycler(list(reversed(DIFFS)), lambda: cfg.difficulty,
                                 lambda v: (setattr(cfg, "difficulty", v), cfg.save()))),
            Option(t("Velocidad de las notas"), value=lambda: decimal(cfg.note_speed, 1),
                   change=num("note_speed", 0.1, 0.5, 2.0)),
            Option(t("Letra"), value=lambda: yes_no(cfg.lyrics),
                   change=cycler([False, True], lambda: cfg.lyrics,
                                 lambda v: (setattr(cfg, "lyrics", v), cfg.save()))),
            Option(t("Volver"), self.menu_back, sep=True),
        ])

    def display_menu(self) -> Menu:
        cfg, num = self.cfg, self.num

        def set_position(v) -> None:
            cfg.position = v
            self.place()
            cfg.save()
        return Menu(t("Pantalla"), [
            Option(t("Opacidad del fondo"), value=lambda: pct(cfg.opacity), change=num("opacity", 0.05, 0.2, 1.0)),
            Option(t("Ancho de la autopista"), value=lambda: f"{cfg.highway_width} px",
                   change=num("highway_width", 40, 320, 1200, self.place)),
            Option(t("Posición"), value=lambda: POSITIONS.get(cfg.position, cfg.position),
                   change=cycler(list(POSITIONS), lambda: cfg.position, set_position)),
            Option(t("Marcador"), value=lambda: SIDES.get(cfg.hud_side, cfg.hud_side),
                   change=cycler(list(SIDES), lambda: cfg.hud_side,
                                 lambda v: (setattr(cfg, "hud_side", v), cfg.save()))),
            Option(t("Volver"), self.menu_back, sep=True),
        ])

    def sound_menu(self) -> Menu:
        cfg, num = self.cfg, self.num
        return Menu(t("Sonido y retardo"), [
            Option(t("Volumen"), value=lambda: pct(cfg.volume),
                   change=num("volume", 0.1, 0.0, 1.0, lambda: setattr(self.player, "volume", cfg.volume))),
            Option(t("Calibrar el retardo"), self.start_calibration, sep=True),
            Option(t("Retardo del audio"), value=lambda: f"{cfg.audio_offset_ms:+.0f} ms",
                   change=num("audio_offset_ms", 5, -300, 500, self.apply_offsets)),
            Option(t("Retardo de AIMP"), value=lambda: f"{cfg.aimp_offset_ms:+.0f} ms",
                   change=num("aimp_offset_ms", 5, -300, 800, self.apply_offsets)),
            Option(t("Retardo de la imagen"), value=lambda: f"{cfg.video_offset_ms:+.0f} ms",
                   change=num("video_offset_ms", 5, -200, 300)),
            Option(t("Volver"), self.menu_back, sep=True),
        ], body=t("Audio: lo que tardan en sonar tus altavoces (lo mide «Calibrar el retardo»).<br>"
                  "AIMP: lo que tarda AIMP en hacer sonar su posición (se mide solo al seguirlo).<br>"
                  "Imagen: lo que tarda la pantalla en enseñar las notas."))

    def controls_menu(self) -> Menu:
        return Menu(t("Guitarra y teclas"), [
            Option(t("Emparejar la guitarra de Wii"), lambda: self.menus.append(self.pairing_menu()),
                   value=lambda: t("conectada") if self.inputs.guitar.connected else ""),
            Option(t("Teclas"), lambda: self.menus.append(self.keys_menu())),
            Option(t("Volver"), self.menu_back, sep=True),
        ])

    def library_short(self) -> str:
        st = self.engine.state
        if st.current:
            return t("generando {pct} %", pct=round(st.done * 100))
        return t("{n} en cola", n=st.pending) if st.pending else ""

    def aimp_offset(self) -> float:
        """Siguiendo a AIMP: su búfer (medido con el loopback) más lo de los altavoces (la calibración)."""
        return self.cfg.aimp_offset_ms + self.cfg.audio_offset_ms

    def apply_offsets(self) -> None:
        is_aimp = isinstance(self.player, AimpPlayer)
        self.player.offset_ms = self.aimp_offset() if is_aimp else self.cfg.audio_offset_ms

    def menu_back(self) -> None:
        menu = self.menus[-1]
        if menu.back():
            return
        if len(self.menus) > 1:
            self.menus.pop()
        elif menu.on_back:
            menu.on_back()

    def place(self) -> None:
        self.cfg.highway_width = int(self.cfg.highway_width)
        place_view(self.view, self.cfg)

    # ---------- calibración ----------

    def start_calibration(self) -> None:
        self.player.pause()
        sr = 48000
        self.calib = Player((calibration.click_track(sr), sr), self.cfg.audio_offset_ms, 0, max(0.5, self.cfg.volume))
        self.calib_strums = []
        self.calib_hits = set()
        self.calib.play()

    def stop_calibration(self) -> None:
        if self.calib:
            self.calib.close()
            self.calib = None

    def finish_calibration(self) -> None:
        strums = self.calib_strums
        self.stop_calibration()
        res = calibration.measure(strums)
        if res is None:
            self.menus.append(Menu(t("Calibración"), [
                Option(t("Repetir"), lambda: (self.menus.pop(), self.start_calibration())),
                Option(t("Volver"), self.menus_pop),
            ], body=t("Pocos rasgueos a tiempo con los clics (hacen falta {n}). Prueba otra vez.",
                      n=calibration.MIN_TAPS)))
            return
        med, n, spread = res
        old = self.cfg.audio_offset_ms
        new = round(old + med)
        body = (t("Rasgueas de media {ms:.0f} ms tarde ({n} rasgueos, ±{spread:.0f} ms).", ms=abs(med), n=n,
                  spread=spread) if med > 0 else
                t("Rasgueas de media {ms:.0f} ms pronto ({n} rasgueos, ±{spread:.0f} ms).", ms=abs(med), n=n,
                  spread=spread))
        body += "<br>" + t("Retardo del audio: {old:+.0f} → <b>{new:+.0f} ms</b>", old=old, new=new)
        if spread > 40:
            body += "<br>" + t("Ha salido bastante irregular: mejor repetirlo.")

        def save() -> None:
            self.cfg.audio_offset_ms = new
            self.apply_offsets()
            self.cfg.save()
            self.menus_pop()
            self.toast(t("Retardo del audio: {new:+.0f} ms", new=new))
        self.menus.append(Menu(t("Calibración"), [
            Option(t("Guardar"), save),
            Option(t("Repetir"), lambda: (self.menus.pop(), self.start_calibration())),
            Option(t("Descartar"), self.menus_pop),
        ], body=body))

    def menus_pop(self) -> None:
        self.menus.pop()

    # ---------- teclas ----------

    def keys_menu(self) -> Menu:
        def value(action: str):
            return lambda: "…" if self.capturing == action else win32.combo_label(keymap(self.cfg.keys)[action])

        def reset() -> None:
            self.cfg.keys = {}
            self.cfg.save()
            self.inputs.set_keys({})
            self.toast(t("Teclas de siempre"))
        return Menu(t("Teclas"), [Option(t(name), lambda a=action: self.capture_key(a), value=value(action))
                                  for action, name, _, _ in ACTIONS]
                    + [Option(t("Restablecer las de siempre"), reset, sep=True),
                       Option(t("Volver"), self.menu_back, sep=True)],
                    body=self.keys_body)

    def keys_body(self) -> str:
        if self.capturing:
            name = ACTION_NAMES[self.capturing]
            return (t("Pulsa la tecla (con Ctrl, Alt o Win) para <b>{name}</b>.", name=name)
                    if self.capturing in GLOBAL_ACTIONS else t("Pulsa la tecla para <b>{name}</b>.", name=name)
                    ) + "<br>" + t("Esc o rojo: cancelar")
        return t("Elige una acción y pulsa la tecla nueva; si otra la usaba, se intercambian.<br>"
                 "Mostrar / ocultar y Salir funcionan siempre, también con el juego oculto.")

    def capture_key(self, action: str) -> None:
        self.capturing = action
        self.inputs.capture_key(action in GLOBAL_ACTIONS)

    def key_captured(self, combo: str) -> None:
        action, self.capturing = self.capturing, None
        if not action or not combo:
            return  # Esc: cancelado
        name = ACTION_NAMES[action]
        if action in GLOBAL_ACTIONS and not ({"ctrl", "alt", "win"} & set(combo.split("+"))
                                             or re.fullmatch(r"f\d+|pause|scrolllock", combo)):
            self.toast(t("«{name}» funciona en todas partes: usa Ctrl, Alt o Win con la tecla "
                         "(si no, esa tecla dejaría de escribir en las demás aplicaciones)", name=name), 7)
            return
        self.cfg.keys = assign(self.cfg.keys, action, combo)
        self.cfg.save()
        self.inputs.set_keys(self.cfg.keys)
        self.toast(f"{name}: {win32.combo_label(combo)}")

    # ---------- entrada ----------

    def handle_inputs(self) -> None:
        for ev in self.inputs.drain():
            if ev.kind == "fret":
                self.held[ev.value] = ev.down
            if ev.kind == "error":
                self.toast(str(ev.value), 6)
            elif ev.kind == "captured":
                self.key_captured(str(ev.value))
            elif self.capturing:  # esperando una tecla nueva: rojo o − (guitarra) cancelan
                if (ev.kind == "fret" and ev.down and ev.value == 1) or (ev.kind == "control" and ev.value == "select"):
                    self.inputs.cancel_capture()
                    self.capturing = None
            elif ev.kind == "control" and ev.value in ("quit", "toggle"):
                QGuiApplication.quit() if ev.value == "quit" else self.toggle_visible()
            elif ev.kind == "control" and ev.value in SONG_COMMANDS:
                self.song_command(ev.value)
            elif self.calib:
                self.calib_input(ev)
            elif self.menus:
                self.menu_input(ev)
            else:
                self.game_input(ev)
        if not self.player.playing or self.menus:  # trastes al día para cuando se siga jugando
            self.game.held = {i for i, h in enumerate(self.held) if h}

    def menu_click(self, row: int) -> None:
        """Clic en la fila row del menú que se ve: se elige esa opción (la que tiene valor, a editarla o dejarla)."""
        if not self.menus or self.calib or self.capturing:
            return
        menu = self.menus[-1]
        rows = menu.view()["rows"]
        if not 0 <= row < len(rows) or rows[row] < 0:  # fuera, o fila vacía de la última página
            return
        if menu.editing and rows[row] != menu.sel:
            menu.editing = False
        menu.sel = rows[row]
        menu.select()

    def menu_wheel(self, steps: int) -> None:
        """Rueda: mueve por la lista (abajo = siguiente) o, editando, cambia el valor (arriba sube)."""
        if self.menus and not self.calib and not self.capturing:
            self.menus[-1].move(steps)

    def watch_right_click(self) -> None:
        """Clic derecho en la autopista (con el ratón pasando a lo de debajo: jugando, sin menú): el menú, como
        Espacio. Con un menú abierto la ventana ya recibe el ratón y el derecho es «volver» (QML)."""
        rc = self.right_click
        if rc is None:
            return
        if rc.clicked.is_set():
            rc.clicked.clear()
            if not self.menus and not self.calib:
                self.pause()
        if self.menus or self.calib or self.dialog_open or not self.view.isVisible():
            rc.rect = None
            return
        left, top, right, bottom = win32.window_rect(int(self.view.winId()))
        half = (right - left) * self.cfg.highway_width / max(1, self.view.width()) / 2  # la autopista, centrada
        mid = (left + right) // 2
        rc.rect = (int(mid - half), top, int(mid + half), bottom)

    def idle_inputs(self) -> None:
        """Con el juego oculto no se pinta (ni se llama a frame): aquí se atiende lo que vale estando oculto."""
        for ev in self.inputs.drain():
            if ev.kind == "error":
                self.toast(str(ev.value), 6)
            elif ev.kind == "control" and ev.value == "quit":
                QGuiApplication.quit()
            elif ev.kind == "control" and ev.value == "toggle":
                self.toggle_visible()
                return  # lo demás, ya con el juego a la vista
            elif ev.kind == "control" and ev.value in SONG_COMMANDS:
                self.song_command(ev.value)
        now = time.perf_counter()
        self.tick_library(now)
        if self.follow:
            self.watch_aimp(now)

    def song_command(self, cmd: str) -> None:
        """Botones 1, 2 y Home del Wiimote: siguiente, anterior y al azar. Siguiendo a AIMP, se le piden a AIMP
        (al azar, una canción con chart de la biblioteca); si no, en el orden de la biblioteca."""
        if self.follow:
            if cmd == "random":
                songs = [e for albums in self.tree().values() for s in albums.values() for e in s
                         if e.folder and e.audio != self.aimp_file]
                if songs and self.aimp.play_file(random.choice(songs).audio):
                    self.toast(t("AIMP: canción al azar"))
            else:
                self.aimp.command(CMD_NEXT if cmd == "next" else CMD_PREV)
                self.toast(t("AIMP: siguiente") if cmd == "next" else t("AIMP: anterior"))
            return
        if cmd == "random":
            self.play_random()
            return
        songs = [e for albums in self.tree().values() for s in albums.values() for e in s if e.folder]
        i = next((k for k, e in enumerate(songs) if e.sha == self.chart.audio_sha256), -1)
        if songs:
            self.choose(songs[(i + (1 if cmd == "next" else -1)) % len(songs)])

    def calib_input(self, ev) -> None:
        if (ev.kind == "strum" and ev.down) or (ev.kind == "control" and ev.value == "enter"):
            ms = self.calib.position_ms(ev.t)
            self.calib_strums.append(ms)
            i = calibration.nearest(ms)
            if i is not None and i not in self.calib_hits:
                self.calib_hits.add(i)
                self.flash_t[CALIB_LANE] = ev.t
        elif (ev.kind == "control" and ev.value in ("select", "back", "start", "pause")) or (
                ev.kind == "fret" and ev.down and ev.value == 1):
            self.stop_calibration()

    def menu_input(self, ev) -> None:
        menu = self.menus[-1]
        if ev.kind == "strum" and not ev.down:
            if self.strum_hold and self.strum_hold[0] == ev.value:
                self.strum_hold = None
            return
        if isinstance(menu, SearchMenu):
            if ev.kind == "char":
                menu.backspace() if ev.value == BACKSPACE else menu.type(ev.value)
                return
        if ev.kind == "strum":
            menu.move(ev.value)
            self.strum_hold = (ev.value, ev.t, ev.t + MENU_REPEAT_S[0])
        elif ev.kind == "fret" and ev.down and ev.value in (0, 1):
            menu.select() if ev.value == 0 else self.menu_back()
        elif ev.kind == "fret" and ev.down and ev.value in (2, 3):
            menu.page(-1 if ev.value == 2 else 1)
        elif ev.kind == "control":
            if ev.value in ("start", "enter"):
                menu.select()
            elif ev.value in ("select", "back"):
                self.menu_back()
            elif ev.value == "pause" and self.menus[0].on_back:
                self.menus[0].on_back()
            elif ev.value == "difficulty":
                self.cycle_difficulty()

    def game_input(self, ev) -> None:
        if ev.kind == "control":
            if ev.value in ("start", "pause", "back"):
                self.pause()
            elif ev.value in ("select", "difficulty"):
                self.cycle_difficulty()
            elif ev.value == "restart":
                self.restart()
            elif ev.value == "enter":
                ev.kind, ev.value = "strum", 1
        if not self.player.playing or self.waiting:
            return
        t = self.player.position_ms(ev.t)
        if ev.kind == "control" and ev.value == "star":
            self.game.activate(t)  # sin media barra no hace nada (los lados de la autopista avisan cuando se puede)
        if ev.kind == "fret":
            self.game.fret(ev.value, ev.down, t)
        elif ev.kind == "strum" and ev.down:
            self.game.strum(t)

    # ---------- cada fotograma ----------

    def frame(self) -> dict:
        now = time.perf_counter()
        if self.resume_at is not None and now >= self.resume_at:
            self.resume_at = None
            self.player.play()
        connected = self.inputs.guitar.connected
        if connected != self.guitar_connected:
            if self.guitar_connected is not None:  # al abrir no se avisa: solo si cambia mientras está abierto
                self.toast(t("Guitarra conectada") if connected else
                           t("Sin guitarra: enciende el Wiimote y se conecta sola (o juega con el teclado)"),
                           TOAST_S if connected else 6)
            self.guitar_connected = connected
        self.handle_inputs()
        self.watch_right_click()
        text = bool(self.menus) and isinstance(self.menus[-1], SearchMenu) and not self.calib
        if text != self.text_mode:
            self.text_mode = text
            self.inputs.set_text_mode(text)
        mouse = bool(self.menus) and not self.calib  # con un menú abierto, el ratón vale para elegir
        if mouse != self.mouse_on:
            self.mouse_on = mouse
            win32.set_click_through(int(self.view.winId()), not mouse)
        if self.strum_hold and (not self.menus or self.calib):
            self.strum_hold = None
        if self.strum_hold and now >= self.strum_hold[2]:  # strum mantenido: sigue desplazando
            d, since, _ = self.strum_hold
            self.menus[-1].move(d)
            self.strum_hold = (d, since, now + MENU_REPEAT_S[1 if now - since < 2 else 2])
        if self.calib and self.calib.finished:
            self.finish_calibration()
        self.watch_aimp(now)
        self.tick_library(now)
        active = not self.waiting and not self.blank  # siguiendo a AIMP sin chart (o sin canciones) no se juega
        seek = self.player.take_seek()
        if seek is not None and active and now > self.own_seek_until:  # salto hecho en AIMP
            self.results = ""
            self.menus = [m for m in self.menus if m.key != "results"]
            self.new_game()
            self.game.skip_to(seek - self.player.offset_ms + SWITCH_AHEAD_MS)
            self.partial = True
        pos = self.player.position_ms(now)
        if self.player.playing and active:
            if self.autoplay:
                self.play_itself(pos)
            self.game.update(pos)
            if self.best_score and not self.partial and not self.record_toast and self.game.stats.score > self.best_score:
                self.record_toast = True
                self.toast(t("¡Nuevo récord!"))
        for kind, _, ns in self.game.events:
            if kind == "hit":
                for f in ns.note.frets:
                    self.flash_t[f] = now
            elif kind == "phrase":
                self.phrase_t = now
                if self.game.star_ready and not self.star_hint and not self.autoplay:
                    self.star_hint = True
                    key = win32.combo_label(keymap(self.cfg.keys)["star"])
                    self.toast(t("Star power listo: levanta la guitarra (o {key})", key=key))
            elif kind == "star":
                self.star_t = now
            elif kind in ("miss", "overstrum"):  # se marca el carril de la nota (o los trastes pulsados)
                self.miss_t = now
                lanes = ns.note.frets if ns is not None else [i for i, h in enumerate(self.held) if h]
                for f in lanes:
                    self.miss_lane_t[f] = now
        self.game.events.clear()
        if active and not self.results and (self.game.finished and pos > self.chart.duration_ms - 500
                                            or self.player.finished):
            self.results = self.finish_song()
            if self.follow:  # AIMP sigue con la siguiente: el resumen, de aviso
                self.toast(self.results.split("<br>")[0].replace("<b>", "").replace("</b>", ""), 6)
            else:
                self.player.pause()
                self.menus = [self.results_menu()]

        travel = TRAVEL_MS / max(0.3, self.cfg.note_speed)
        lyrics = {}
        if self.calib:
            notes, beats = self.calib_notes(now, travel)
        elif not active:
            notes, beats = [], []
        else:
            notes, beats = self.song_notes(now, travel)
            if self.cfg.lyrics and self.lyrics:
                lyrics = self.lyrics.view(self.player.position_ms(now + self.cfg.video_offset_ms / 1000))

        st = self.game.stats
        countdown = 0.0
        if self.resume_at is not None:
            countdown = self.resume_at - now
        elif self.player.playing and pos < 0 and not self.game.stats.hits:
            countdown = -pos / 1000
        menu = self.menus[-1].view() if self.menus and not self.calib else {}
        calib = {}
        if self.calib:
            calib = {"taps": len(self.calib_hits), "total": calibration.CLICKS,
                     "progress": min(1.0, self.calib.position_ms() / calibration.click_times_ms()[-1])}
        burn = self.game.sustaining_frets
        return {
            "notes": notes, "beats": beats, "time": now,
            "held": self.held if not self.menus else [False] * 5,  # en los menús no se encienden los botones
            "flash": [max(0.0, 1 - (now - ft) / 0.3) for ft in self.flash_t],
            "burn": [i in burn for i in range(5)],
            "missFlash": max(0.0, 1 - (now - self.miss_t) / 0.35),
            "missLane": [max(0.0, 1 - (now - mt) / 0.4) for mt in self.miss_lane_t],
            "score": st.score, "streak": st.streak, "mult": st.multiplier, "baseMult": st.base_multiplier,
            "accuracy": st.accuracy,
            "star": self.game.energy, "starOn": st.star, "starReady": self.game.star_ready,
            "phraseFlash": max(0.0, 1 - (now - self.phrase_t) / PHRASE_FLASH_S),
            "starFlash": max(0.0, 1 - (now - self.star_t) / 0.8),
            "title": ("Music Hero" if self.blank else f"AIMP · {self.aimp_title}" if not active
                      else f"{self.chart.artist} – {self.chart.title}"),
            "difficulty": DIFF_NAMES[self.difficulty],
            "autoplay": self.autoplay, "best": self.best_score, "partial": self.partial,
            "progress": max(0.0, min(1.0, pos / max(1, self.chart.duration_ms))),
            "countdown": countdown, "menu": menu, "calib": calib,
            "menuHint": t(LONG_HINT if self.menus[-1].long else MENU_HINT) if menu else "",
            "toast": self.toast_text if now < self.toast_until else (self.waiting if not self.menus else ""),
            "message": self.message, "opacity": self.cfg.opacity, "hwWidth": self.cfg.highway_width,
            "lyricsOn": self.cfg.lyrics, "lyrics": lyrics, "hudSide": self.cfg.hud_side, "lang": lang(),
        }

    def calib_notes(self, now: float, travel: float) -> tuple[list, list]:
        """Una nota por clic medido, en el carril del centro; las rasgueadas desaparecen."""
        tv = self.calib.position_ms(now + self.cfg.video_offset_ms / 1000)
        notes, beats = [], []
        for i, c in enumerate(calibration.scored_clicks_ms()):
            u = (c - tv) / travel
            if -BEHIND_MS / travel <= u <= 1.02:
                beats += [u, 1]
                if i not in self.calib_hits:
                    notes += [CALIB_LANE, u, u, 2 if u < -calibration.MAX_DEV_MS / travel else 0, 0, 0, 1, 0]
        return notes, beats

    def song_notes(self, now: float, travel: float) -> tuple[list, list]:
        tv = self.player.position_ms(now + self.cfg.video_offset_ms / 1000)
        notes = []
        start = bisect.bisect_left(self.times, tv - BEHIND_MS - self.max_sustain)
        for ns in self.game.notes[start:]:
            n = ns.note
            u = (n.time_ms - tv) / travel
            if u > 1.02:
                break
            u_end = min(1.02, (n.time_ms + n.sustain_ms - tv) / travel) if n.sustain_ms else u
            if ns.state == SKIPPED or u_end < -BEHIND_MS / travel or (ns.state == HIT and not n.sustain_ms):
                continue
            state = ns.state
            if ns.state == HIT and not ns.sustaining:
                if ns.sustain_until >= n.time_ms + n.sustain_ms - 1:
                    continue  # sustain completo
                state = MISSED  # soltado antes: la cola en gris
            star = int(self.game.is_star(ns))
            for f in n.frets:
                notes += [f, max(u, -0.25), u_end, state, int(n.hopo), int(ns.sustaining), len(n.frets), star]
            if len(notes) >= 8 * 200:
                break
        beats = []
        i = bisect.bisect_left(self.beat_times, tv - BEHIND_MS)
        for bt, bar in self.beats[i:i + 32]:
            u = (bt - tv) / travel
            if u > 1.02:
                break
            beats += [u, int(bar)]
        return notes, beats

    def play_itself(self, t: float) -> None:
        """Modo automático: toca cada nota a su tiempo y mantiene los trastes hasta la siguiente; el star power,
        en cuanto se puede."""
        g = self.game
        if g.star_ready:
            g.activate(t)
        while g.next < len(g.notes) and g.notes[g.next].note.time_ms <= t:
            ns = g.notes[g.next]
            g.held = set(ns.note.frets)
            self.held = [i in g.held for i in range(5)]
            g.strum(ns.note.time_ms)

    def finish_song(self) -> str:
        """Guarda la partida (si cuenta) y devuelve el resumen para el menú del final."""
        st = self.game.stats
        total = sum(ns.state != SKIPPED for ns in self.game.notes)
        play = Play(round(st.score), round(st.accuracy, 4), st.hits, total, st.best_streak, st.overstrums)
        if self.partial:
            record = t("No cuenta para récords (modo automático o empezada a mitad)") + "<br>" + self.record_line()
        else:
            prev = self.records.add_play(self.chart.audio_sha256, self.difficulty, play,
                                         self.chart.title, self.chart.artist)
            self.best_score = max(self.best_score, play.score)
            if prev is None:
                record = self.record_line()
            elif prev.score == 0 and play.score == 0:
                record = t("Primera partida en {name}", name=DIFF_NAMES[self.difficulty])
            elif prev.score == 0:
                record = "<font color='#ffdc00'><b>" + t("¡Primer récord!") + "</b></font>"
            else:
                record = ("<font color='#ffdc00'><b>" + t("¡Nuevo récord!") + "</b></font> "
                          + t("(+{diff}; antes {old})", diff=fmt_int(play.score - prev.score), old=fmt_int(prev.score)))
        return self.summary(play, record)

    def summary(self, play: Play, record: str) -> str:
        st = self.game.stats
        head = t("{name}: {hits}/{total} notas ({acc:.0%})", name=DIFF_NAMES[self.difficulty], hits=play.hits,
                 total=play.total, acc=play.accuracy)
        lines = ["<b>" + head + (" · " + t("¡sin fallos!") if play.full_combo else "") + "</b>",
                 t("Puntos: {score}", score=fmt_int(play.score)),
                 t("Mejor racha: {streak} · Strums de más: {over}", streak=st.best_streak, over=st.overstrums)
                 + (" · " + t("Star power: {n}/{total} frases", n=st.phrases, total=len(self.game.phrase_left))
                    if self.game.phrase_left else ""),
                 record]
        if len(st.offsets) >= 20:
            offs = sorted(st.offsets)
            med = offs[len(offs) // 2]
            if abs(med) < 3:
                lines.append(t("Tus strums van justo a tiempo"))
            else:
                lines.append((t("Tus strums van de media {ms:.0f} ms tarde", ms=abs(med)) if med > 0 else
                              t("Tus strums van de media {ms:.0f} ms pronto", ms=abs(med)))
                             + (" " + t("(si te pasa siempre, calibra el retardo)") if abs(med) > 25 else ""))
        return "<br>".join(lines)


def pct(v: float) -> str:
    return f"{round(v * 100)} %"


def yes_no(v: bool) -> str:
    return t("Sí") if v else t("No")


def decimal(v: float, digits: int) -> str:
    """Con coma en español y punto en inglés."""
    s = f"{v:.{digits}f}"
    return s.replace(".", ",") if lang() == "es" else s


def fmt_int(n: float) -> str:
    s = f"{round(n):,}"
    return s.replace(",", ".") if lang() == "es" else s


def fmt_date(iso: str) -> str:
    if len(iso) < 10:
        return iso
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if lang() == "es" else iso[:10]


class Bridge(QObject):
    def __init__(self):
        super().__init__()
        self.session: Session | None = None

    @Slot(result="QVariantMap")
    def tick(self) -> dict:
        return self.session.frame() if self.session else {}

    # ratón en los menús (solo recibe clics con un menú abierto: el resto del tiempo el juego deja pasarlos)
    @Slot(int)
    def menuClick(self, row: int) -> None:  # noqa: N802 - nombre para QML
        if self.session:
            self.session.menu_click(row)

    @Slot(int)
    def menuWheel(self, steps: int) -> None:  # noqa: N802
        if self.session:
            self.session.menu_wheel(steps)

    @Slot()
    def menuBack(self) -> None:  # noqa: N802
        if self.session and self.session.menus and not self.session.capturing:
            self.session.menu_back()

    @Slot(str, result=str)
    def tr(self, text: str) -> str:
        """Los textos fijos del QML, traducidos (bridge.tr("..."))."""
        return t(text)


def icon_pixmap(size: int) -> QPixmap:
    """La autopista en pequeño: cinco carriles de colores que se juntan hacia arriba, sin fondo. Se dibuja en
    una rejilla de 64 escalada a size (nítido también a 256 para el icono del .exe)."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 64, size / 64)
    p.setPen(Qt.PenStyle.NoPen)
    colors = ["#2ecc40", "#ff4136", "#ffdc00", "#1e90ff", "#ff851b"]
    for i, c in enumerate(colors):  # abajo de 2 a 62, arriba de 19 a 45
        x0, x1 = 2 + i * 12, 19 + i * 5.2
        p.setBrush(QColor(c))
        p.drawPolygon(QPolygonF([QPointF(x0 + 1, 62), QPointF(x0 + 11, 62), QPointF(x1 + 4.6, 2), QPointF(x1 + 0.6, 2)]))
    p.setBrush(QColor("#151527"))  # la línea de golpeo, blanca con borde oscuro: se ve en barras claras y oscuras
    p.drawRect(QRectF(1, 46, 62, 7))
    p.setBrush(QColor("white"))
    p.drawRect(QRectF(2, 47.5, 60, 4))
    p.end()
    return pix


def tray_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 256):
        icon.addPixmap(icon_pixmap(s))
    return icon


def make_tray(app: QApplication, session: Session) -> QSystemTrayIcon | None:
    """Icono junto al reloj: un clic muestra u oculta el juego; con el derecho, el menú (y Salir)."""
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    tray = QSystemTrayIcon(tray_icon(), app)
    menu = QMenu()
    toggle = menu.addAction(t("Mostrar / ocultar"), session.toggle_visible)
    status = menu.addAction(t("Biblioteca"))
    status.setEnabled(False)  # solo informa
    menu.addSeparator()
    leave = menu.addAction(t("Salir"), app.quit)

    def refresh() -> None:  # el atajo (se puede cambiar), el idioma y lo que suena, al abrir el menú o pasar por encima
        key = win32.combo_label(keymap(session.cfg.keys)["toggle"])
        toggle.setText((t("Ocultar ({key})", key=key) if session.view.isVisible()
                        else t("Mostrar ({key})", key=key)))
        song = f"AIMP: {session.aimp_title}" if session.follow else f"{session.chart.artist} – {session.chart.title}"
        status.setText(t("Biblioteca: {line}", line=session.library_line()))
        leave.setText(t("Salir"))
        tray.setToolTip(f"Music Hero · {song}" if not session.blank else "Music Hero")
    menu.aboutToShow.connect(refresh)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: session.toggle_visible()
                           if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    refresh()
    tray.show()
    tray._menu = menu  # que no lo recoja el recolector
    return tray


def place_view(view: QQuickView, cfg: Config) -> None:
    geo = QGuiApplication.primaryScreen().availableGeometry()
    w = min(geo.width(), cfg.highway_width + SIDE_MARGIN)
    x = {"left": geo.x(), "right": geo.x() + geo.width() - w}.get(cfg.position, geo.x() + (geo.width() - w) // 2)
    view.setGeometry(x, geo.y(), w, geo.height())


def make_view(cfg: Config, bridge: Bridge) -> QQuickView:
    view = QQuickView()
    # sin WindowTransparentForInput de Qt (descartaría el ratón también en los menús): los clics los deja pasar
    # el estilo WS_EX_TRANSPARENT (win32.make_click_through / set_click_through), que se quita con un menú abierto
    view.setFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                  | Qt.WindowType.WindowDoesNotAcceptFocus)
    view.setColor(QColor(0, 0, 0, 0))
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.setProperty("_q_showWithoutActivating", True)
    place_view(view, cfg)
    view.rootContext().setContextProperty("bridge", bridge)
    view.engine().addImageProvider("sprites", SpriteProvider())
    view.setSource(QUrl.fromLocalFile(str(QML)))
    for err in view.errors():
        print("QML:", err.toString())
    return view


def resolve(path: Path) -> Chart:
    if path.is_file() and path.suffix.lower() != ".json":
        folder = find_chart(path)
        if folder is None:
            sys.exit(t("No hay chart para {name}; genérala con: uv run --project generator generate \"{path}\"",
                       name=path.name, path=path))
        chart = Chart.load(folder)
        chart.audio_file = path
        return chart
    chart = Chart.load(path)
    if not chart.audio_file.exists():
        sys.exit(t("No encuentro el audio de la chart: {file}", file=chart.audio_file))
    return chart


def install_engine() -> int:
    """--install-engine: lo mismo que «Instalar el motor» del menú, sin juego (para instalaciones automáticas)."""
    inst = installer.EngineInstaller()
    inst.start()
    last = ""
    while inst.state == "running":
        if inst.step != last:
            last = inst.step
            print(f"{round(inst.done * 100):3d} % {last}")
        time.sleep(0.5)
    print(t("motor instalado") if inst.state == "done" else t("error: {err}", err=inst.error))
    return 0 if inst.state == "done" else 1


def main() -> int:
    cfg = Config.load()
    set_language(cfg.language)  # antes de escribir nada (consola, log, ayuda)
    parser = argparse.ArgumentParser(description=t(USAGE), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("song", type=Path, nargs="?",
                        help=t("audio (busca su chart en out/charts) o carpeta de chart; sin ella, el selector"))
    parser.add_argument("--difficulty", choices=DIFFS,
                        help=t("por defecto, la última elegida en esa canción o, si no, la de por defecto (Ajustes)"))
    parser.add_argument("--speed", type=float, help=t("velocidad de las notas (1 = normal); el menú la guarda"))
    parser.add_argument("--screenshot", type=Path, help=t("guarda una captura a los N s (--screenshot-at) y sale"))
    parser.add_argument("--screenshot-at", type=float, default=8.0)
    parser.add_argument("--screenshot-menu", action="store_true", help=t("con --screenshot: abre el menú antes"))
    parser.add_argument("--autoplay", action="store_true", help=t("modo automático: el juego toca solo"))
    parser.add_argument("--hidden", action="store_true", help=t("empezar oculto (Ctrl+Alt+H lo muestra)"))
    parser.add_argument("--install-engine", action="store_true",
                        help=t("(app instalada) instalar el motor de generación sin abrir el juego, y salir"))
    if FROZEN or sys.stdout is None:  # instalada (sin consola): a un log
        APP_LOG.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(APP_LOG, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        print(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(sys.argv[1:])}")
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    args = parser.parse_args()
    if args.install_engine:
        return install_engine()
    if not win32.single_instance("MusicHero.play"):
        print(t("Music Hero ya está abierto"))
        return 0

    if args.speed:
        cfg.note_speed = args.speed
    records = Records()
    if args.song:
        chart = resolve(args.song)
    else:  # el selector, empezando por la última canción jugada
        entries = scan()
        if entries:
            e = next((e for e in entries if e.sha == records.last), entries[0])
            chart = Chart.load(Path(e.folder))
            chart.audio_file = Path(e.audio)
        else:  # recién instalado: la bienvenida (añadir la carpeta de música)
            chart = blank_chart()

    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv)  # con widgets por el icono junto al reloj y su menú
    app.setQuitOnLastWindowClosed(False)  # oculto sigue vivo: se sale desde el icono o con el atajo
    bridge = Bridge()
    view = make_view(cfg, bridge)

    inputs = Inputs(cfg.keys)
    inputs.start()
    inputs.set_game_keys(True)
    for e in inputs.errors:
        print(t("aviso: {msg}", msg=e))
    aimp = Aimp()
    engine = EngineClient()
    session = bridge.session = Session(chart, cfg, args.difficulty, inputs, view, records, aimp, engine)
    session.set_autoplay(args.autoplay)
    session.tray = make_tray(app, session)
    session.right_click = win32.RightClick()
    if not args.song and not (aimp.connected() and aimp.state() == PLAYING and session.follow_aimp()):
        session.open_selector()  # si suena AIMP, se le sigue; si no, a elegir canción
    if args.hidden:
        if not session.follow:
            session.pause()
        inputs.set_game_keys(False)

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer()  # deja que Python atienda Ctrl+C
    keepalive.start(200)
    keepalive.timeout.connect(lambda: None)
    topmost = QTimer()
    topmost.timeout.connect(lambda: view.isVisible() and not session.dialog_open
                            and win32.bring_to_top(int(view.winId())))
    topmost.start(500)
    idle = QTimer()  # oculto no se pinta: el atajo, salir y los botones del Wiimote se atienden aquí
    idle.timeout.connect(lambda: None if view.isVisible() else session.idle_inputs())
    idle.start(50)
    if args.screenshot:
        def shot() -> None:  # solo la ventana del juego, con su transparencia
            view.grabWindow().save(str(args.screenshot))
            app.quit()
        if args.screenshot_menu:
            QTimer.singleShot(int(args.screenshot_at * 1000) - 300, bridge.session.pause)
        QTimer.singleShot(int(args.screenshot_at * 1000), shot)

    if not args.hidden:
        view.show()
        win32.make_click_through(int(view.winId()))
    playing = (f"AIMP: {session.aimp_title}" if session.follow else t("sin canciones todavía") if session.blank
               else f"{session.chart.artist} - {session.chart.title}")
    keys = {a: win32.combo_label(k) for a, k in keymap(cfg.keys).items()}
    print(f"{playing} ({DIFF_NAMES[session.difficulty]}). "
          + t("+ / {pause}: menú, − / {diff}: dificultad, {toggle} muestra/oculta, {quit} sale (o el icono junto "
              "al reloj).", pause=keys["pause"], diff=keys["difficulty"], toggle=keys["toggle"], quit=keys["quit"]))
    try:
        return app.exec()
    finally:
        inputs.stop()
        engine.stop()
        session.right_click.stop()
        session.stop_calibration()
        session.player.close()


if __name__ == "__main__":
    sys.exit(main())
