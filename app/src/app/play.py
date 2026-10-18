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
(dificultad, ajustes, calibración); − o Tab cambian de dificultad sin parar. Ctrl+Alt+H muestra/oculta;
Ctrl+Alt+Q sale. Ajustes en %APPDATA%/MusicHero/config.json (se guardan solos desde el menú).
"""

from __future__ import annotations

import argparse
import bisect
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap, QPolygonF, QSurfaceFormat
from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import calibration, loopback, win32
from .aimp import CMD_NEXT, CMD_PAUSE, CMD_PREV, PLAYING, Aimp, AimpPlayer, Track
from .chart import DIFF_NAMES, DIFFS, ROOT, Chart, find_chart
from .config import Config
from .gameplay import HIT, MISSED, SKIPPED, Game
from .inputs import ACTION_NAMES, ACTIONS, GLOBAL_ACTIONS, Inputs, assign, keymap
from .library import Entry, group, scan, search
from .lyrics import Lyrics
from .menu import Menu, Option, SearchMenu, cycler, stepper
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
MENU_HINT = "Strum: mover · Verde / +: elegir · Rojo / −: volver"
LONG_HINT = MENU_HINT + " · Amarillo / Azul: pasar página"
POSITIONS = {"left": "Izquierda", "center": "Centro", "right": "Derecha"}
MENU_REPEAT_S = (0.35, 0.08, 0.035)  # strum mantenido en un menú: espera, repetición y, pasados 2 s, más rápido
SIDES = {"left": "Izquierda", "right": "Derecha"}
AIMP_CHECK_S = 0.3  # cada cuánto se mira qué canción tiene AIMP
OWN_SEEK_S = 0.6  # los saltos que hace el propio juego en AIMP (reiniciar) no cuentan como saltos del usuario
GENERATE_LOG = ROOT / "out" / "generate_aimp.log"
SONG_COMMANDS = ("next", "prev", "random")  # botones 1, 2 y Home del Wiimote


class Session(QObject):
    def __init__(self, chart: Chart, cfg: Config, difficulty: str | None, inputs: Inputs, view: QQuickView,
                 records: Records | None = None, aimp: Aimp | None = None):
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
        self.gen_proc: subprocess.Popen | None = None  # chart generándose en segundo plano
        self.gen_file, self.gen_name = "", ""
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
        self.hidden_hint = False  # ya se avisó de que oculto sigue en el icono
        self.strum_hold: tuple[int, float, float] | None = None  # strum mantenido en un menú: (dirección, desde, siguiente)
        self.message = "; ".join(inputs.errors)
        self.autoplay = False
        self.partial = False  # la partida no cuenta para récords (automático o empezada a mitad)
        self.record_toast = False  # ya se avisó de que se ha superado el récord en esta partida
        self.load_song(chart, difficulty)

    def load_song(self, chart: Chart, difficulty: str | None = None, player: AimpPlayer | None = None) -> None:
        """Pone esta canción (al empezar, desde el selector o la que suena en AIMP, con player): su dificultad es
        la pedida, la última elegida en ella o la de por defecto."""
        self.stop_calibration()
        player = player or Player(chart.audio_file, self.cfg.audio_offset_ms, LEAD_IN_MS, self.cfg.volume)
        if self.player:
            self.player.close()
        self.chart, self.player = chart, player
        self.lyrics = Lyrics.load(chart.folder, chart.audio_sha256)
        d = difficulty or self.records.difficulty(chart.audio_sha256) or self.cfg.difficulty
        self.difficulty = d if d in chart.difficulties else next(iter(chart.difficulties))
        self.beats = chart.beats
        self.beat_times = [b[0] for b in self.beats]
        self.menus.clear()
        self.results, self.resume_at = "", None
        self.flash_t, self.miss_lane_t, self.miss_t = [0.0] * 5, [0.0] * 5, 0.0
        self.records.set_last(chart.audio_sha256)
        self.new_game()
        if self.player.lead_in:  # el propio; AIMP ya está sonando (o en pausa, como lo haya dejado el usuario)
            self.player.play()

    # ---------- partida ----------

    def new_game(self) -> None:
        notes = self.chart.difficulties[self.difficulty]
        self.game = Game(notes)
        self.game.held |= {i for i, h in enumerate(self.held) if h}
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
        self.toast(f"Dificultad: {DIFF_NAMES[d]}")
        if self.results:
            return  # se juega al elegir "Otra vez"
        t = self.player.position_ms()
        self.new_game()
        if t > 0:
            self.game.skip_to(t + (SWITCH_AHEAD_MS if self.player.playing else 0))
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
            if self.tray and not self.hidden_hint:
                self.hidden_hint = True
                key = win32.combo_label(keymap(self.cfg.keys)["toggle"])
                self.tray.showMessage("Music Hero sigue aquí", f"{key} o un clic en este icono para volver; "
                                      "para salir, clic derecho en el icono.", QSystemTrayIcon.MessageIcon.NoIcon, 4000)
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
            self.toast("AIMP no tiene ninguna canción puesta")
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
        self.check_generation()
        if not self.follow:
            return
        if not self.aimp.connected():
            self.stop_following()
            self.load_song(self.chart)
            self.pause()
            self.toast("AIMP se ha cerrado: vuelve el reproductor propio", 5)
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
                print(f"medida del retardo de AIMP: {err}")
                lag = None
            print(f"retardo de AIMP: {lag:+.0f} ms" if lag is not None else "retardo de AIMP: no se pudo medir")
            self.sync_result = (player, lag)
        self.sync_thread = threading.Thread(target=run, daemon=True, name="sincronía")
        self.sync_thread.start()

    def open_aimp_track(self, track: Track) -> None:
        self.aimp_title = track.title or Path(track.file).stem
        try:
            chart = self.chart_for(track.file)
        except Exception as err:  # noqa: BLE001 - una chart rota no tira el juego
            print(f"chart de {track.file}: {err}")
            chart = None
        if chart is None:
            generating = self.gen_proc is not None and self.gen_file == track.file
            self.waiting = (f"«{self.aimp_title}» no tiene chart todavía"
                            + (" (generándola…)" if generating else ": + / Espacio para generarla"))
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
        """Genera en segundo plano la chart de la canción de AIMP (Demucs, modelo y letra: ~1 min con GPU)."""
        uv = shutil.which("uv")
        if self.gen_proc is not None or not self.aimp_file or uv is None:
            self.toast("Ya se está generando otra" if self.gen_proc else "No se puede generar (¿falta uv?)")
            return
        GENERATE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(GENERATE_LOG, "w", encoding="utf-8") as log:  # el proceso hereda su propia copia
            flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
            env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}  # el del juego no es el del generador
            self.gen_proc = subprocess.Popen(
                [uv, "run", "--project", str(ROOT / "generator"), "generate", self.aimp_file],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, creationflags=flags, env=env)
        self.gen_file, self.gen_name = self.aimp_file, self.aimp_title
        self.waiting = f"«{self.aimp_title}» no tiene chart todavía (generándola…)"
        self.resume()

    def check_generation(self) -> None:
        if self.gen_proc is None or self.gen_proc.poll() is None:
            return
        ok = self.gen_proc.returncode == 0
        self.gen_proc = None
        self._by_path = self._tree = None  # índice nuevo: ya está la chart
        current = self.follow and self.aimp_file == self.gen_file
        if not ok:
            self.toast(f"No se pudo generar la chart de {self.gen_name} (out/generate_aimp.log)", 8)
            if current:
                self.waiting = f"«{self.gen_name}» no tiene chart: falló al generarla"
            return
        track = self.aimp.track() if current else None
        if track is not None and track.file == self.gen_file:
            self.open_aimp_track(track)
        else:
            self.toast(f"Chart de {self.gen_name} lista", 5)

    # ---------- menús ----------

    def difficulty_option(self) -> Option:
        avail = [d for d in reversed(DIFFS) if d in self.chart.difficulties]  # de Fácil a Experto: arriba sube
        return Option("Dificultad", value=lambda: DIFF_NAMES[self.difficulty],
                      change=cycler(avail, lambda: self.difficulty, self.set_difficulty))

    def set_autoplay(self, on: bool) -> None:
        self.autoplay = on
        if on:
            self.partial = True  # las partidas con el modo automático no cuentan para récords

    def autoplay_option(self) -> Option:
        return Option("Modo automático", value=lambda: "Sí" if self.autoplay else "No",
                      change=cycler([False, True], lambda: self.autoplay, self.set_autoplay))

    def record_line(self) -> str:
        sha = self.chart.audio_sha256
        best = self.records.best(sha, self.difficulty)
        name = DIFF_NAMES[self.difficulty]
        if best is None:
            return f"Sin récord en {name} todavía"
        st = self.records.stats(sha, self.difficulty)
        line = (f"Récord en {name}: <b>{fmt_int(best.score)}</b> · {best.accuracy:.0%} · racha {best.best_streak}"
                f"{' · sin fallos' if best.full_combo else ''}")
        return line + f"<br>{st.get('plays', 0)} partidas · el {fmt_date(best.date)}"

    # ---------- selector de canciones ----------

    def tree(self) -> dict[str, dict[str, list[Entry]]]:
        if self._tree is None:
            self._tree = group(scan())
        return self._tree

    def song_value(self, e: Entry) -> str:
        """A la derecha de cada canción: su récord (en la dificultad que se le pondría) y la duración."""
        d = self.records.difficulty(e.sha) or self.cfg.difficulty
        best = self.records.best(e.sha, d)
        length = f"{e.duration_ms // 60000}:{e.duration_ms // 1000 % 60:02d}"
        return f"{fmt_int(best.score)} · {length}" if best else length

    def open_selector(self) -> None:
        """Artistas -> álbumes -> canciones, abierto ya en la canción que suena (rojo / − va subiendo)."""
        self.pause()
        tree = self.tree()
        if not tree:
            self.toast("No hay canciones con chart en out/charts")
            return
        here = next(((a, al, i) for a, albums in tree.items() for al, songs in albums.items()
                     for i, e in enumerate(songs) if e.sha == self.chart.audio_sha256), None)
        total = sum(len(s) for albums in tree.values() for s in albums.values())
        root = Menu("Canciones", [Option("Buscar", self.open_search), Option("Al azar", self.play_random)] + [
            Option(a, lambda a=a: self.open_artist(a), value=str(sum(len(s) for s in tree[a].values())))
            for a in tree], body=f"{total} canciones de {len(tree)} artistas")
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
                             for al in albums], body=f"{len(albums)} álbumes")
        self.menus.append(menu)
        if album in albums:
            menu.sel = list(albums).index(album)
            self.open_album(artist, album, song)

    def open_album(self, artist: str, album: str, song: int = 0) -> None:
        songs = self.tree()[artist][album]
        menu = Menu(album, [Option(e.title, lambda e=e: self.choose(e), value=self.song_value(e)) for e in songs],
                    body=f"{artist} · {len(songs)} canciones")
        menu.sel = min(song, len(songs) - 1)
        self.menus.append(menu)

    def open_search(self) -> None:
        """Buscador por título, artista o álbum (teclado directo, o letra a letra con la guitarra)."""
        self.pause()
        entries = [e for albums in self.tree().values() for s in albums.values() for e in s]

        def results(query: str) -> list[Option]:
            return [Option(e.title, lambda e=e: self.choose(e), value=e.group_artist)
                    for e in search(entries, query)]
        self.menus.append(SearchMenu("Buscar canción", results))

    def choose(self, e: Entry) -> None:
        if e.sha == self.chart.audio_sha256:
            self.restart()
            return
        self.toast(f"Cargando {e.title}…", 10)
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
            self.toast(f"No se pudo abrir {e.title}: {err}", 6)
            return
        self.toast(f"{chart.artist} – {chart.title} · {DIFF_NAMES[self.difficulty]}")

    def play_random(self) -> None:
        songs = [e for albums in self.tree().values() for s in albums.values() for e in s
                 if e.sha != self.chart.audio_sha256]
        if songs:
            self.choose(random.choice(songs))

    def pause_menu(self) -> Menu:
        extra = []
        if self.waiting and self.gen_proc is None:
            extra.append(Option("Generar la chart", self.generate_current))
        if not self.follow and self.aimp.connected() and self.aimp.track() is not None:
            extra.append(Option("Seguir a AIMP", self.follow_from_menu))
        return Menu("Pausa", [
            Option("Continuar", self.resume),
            *extra,
            Option("Cambiar canción", self.open_selector),
            Option("Canción al azar", self.play_random),
            Option("Buscar canción", self.open_search),
            self.difficulty_option(),
            self.autoplay_option(),
            Option("Reiniciar", self.restart),
            Option("Ajustes", lambda: self.menus.append(self.settings_menu())),
            Option("Calibrar el retardo", self.start_calibration),
            self.leave_option(),
        ], body=self.pause_body, on_back=self.resume)

    def leave_option(self) -> Option:
        """Con el icono junto al reloj, ocultar (se sale desde el icono); sin él, salir."""
        return Option("Ocultar", self.toggle_visible) if self.tray else Option("Salir", QGuiApplication.quit)

    def pause_body(self) -> str:
        if self.waiting:
            return f"AIMP: {self.waiting}"
        source = "AIMP · " if self.follow else ""
        return f"{source}{self.chart.artist} – {self.chart.title}<br>{self.record_line()}"

    def results_menu(self) -> Menu:
        return Menu("Fin de la canción", [
            Option("Otra vez", self.restart),
            Option("Otra canción", self.open_selector),
            Option("Canción al azar", self.play_random),
            Option("Buscar canción", self.open_search),
            self.difficulty_option(),
            self.autoplay_option(),
            Option("Ajustes", lambda: self.menus.append(self.settings_menu())),
            Option("Calibrar el retardo", self.start_calibration),
            self.leave_option(),
        ], body=lambda: self.results)

    def num(self, name: str, step: float, lo: float, hi: float, after=None):
        """change() para un ajuste numérico de la config: con paso y límites, y se guarda solo."""
        def set_(v: float) -> None:
            setattr(self.cfg, name, v)
            if after:
                after()
            self.cfg.save()
        return stepper(lambda: getattr(self.cfg, name), set_, step, lo, hi)

    def settings_menu(self) -> Menu:
        cfg, num = self.cfg, self.num

        def set_position(v) -> None:
            cfg.position = v
            self.place()
            cfg.save()

        def pct(v: float) -> str:
            return f"{round(v * 100)} %"

        return Menu("Ajustes", [
            Option("Dificultad por defecto", value=lambda: DIFF_NAMES.get(cfg.difficulty, cfg.difficulty),
                   change=cycler(list(reversed(DIFFS)), lambda: cfg.difficulty,
                                 lambda v: (setattr(cfg, "difficulty", v), cfg.save()))),
            Option("Velocidad de las notas", value=lambda: f"{cfg.note_speed:.1f}".replace(".", ","),
                   change=num("note_speed", 0.1, 0.5, 2.0)),
            Option("Volumen", value=lambda: pct(cfg.volume),
                   change=num("volume", 0.1, 0.0, 1.0, lambda: setattr(self.player, "volume", cfg.volume))),
            Option("Retardo", lambda: self.menus.append(self.delay_menu())),
            Option("Opacidad del fondo", value=lambda: pct(cfg.opacity), change=num("opacity", 0.05, 0.2, 1.0)),
            Option("Ancho de la autopista", value=lambda: f"{cfg.highway_width} px",
                   change=num("highway_width", 40, 320, 1200, self.place)),
            Option("Posición", value=lambda: POSITIONS.get(cfg.position, cfg.position),
                   change=cycler(list(POSITIONS), lambda: cfg.position, set_position)),
            Option("Marcador", value=lambda: SIDES.get(cfg.hud_side, cfg.hud_side),
                   change=cycler(list(SIDES), lambda: cfg.hud_side,
                                 lambda v: (setattr(cfg, "hud_side", v), cfg.save()))),
            Option("Teclas", lambda: self.menus.append(self.keys_menu())),
            Option("Letra", value=lambda: "Sí" if cfg.lyrics else "No",
                   change=cycler([False, True], lambda: cfg.lyrics,
                                 lambda v: (setattr(cfg, "lyrics", v), cfg.save()))),
            Option("Volver", self.menu_back),
        ], body="Elige una opción para cambiarla con el strum; se guarda sola.")

    def delay_menu(self) -> Menu:
        cfg, num = self.cfg, self.num
        return Menu("Retardo", [
            Option("Del audio", value=lambda: f"{cfg.audio_offset_ms:+.0f} ms",
                   change=num("audio_offset_ms", 5, -300, 500, self.apply_offsets)),
            Option("De AIMP", value=lambda: f"{cfg.aimp_offset_ms:+.0f} ms",
                   change=num("aimp_offset_ms", 5, -300, 800, self.apply_offsets)),
            Option("De la imagen", value=lambda: f"{cfg.video_offset_ms:+.0f} ms",
                   change=num("video_offset_ms", 5, -200, 300)),
            Option("Volver", self.menu_back),
        ], body="Audio: lo que tardan en sonar tus altavoces (lo mide «Calibrar el retardo»).<br>"
                "AIMP: lo que tarda AIMP en hacer sonar su posición (se mide solo al seguirlo).<br>"
                "Imagen: lo que tarda la pantalla en enseñar las notas.")

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
            self.menus.append(Menu("Calibración", [
                Option("Repetir", lambda: (self.menus.pop(), self.start_calibration())),
                Option("Volver", self.menus_pop),
            ], body=f"Pocos rasgueos a tiempo con los clics (hacen falta {calibration.MIN_TAPS}). "
                    "Prueba otra vez."))
            return
        med, n, spread = res
        old = self.cfg.audio_offset_ms
        new = round(old + med)
        when = "tarde" if med > 0 else "pronto"
        body = (f"Rasgueas de media {abs(med):.0f} ms {when} ({n} rasgueos, ±{spread:.0f} ms).<br>"
                f"Retardo del audio: {old:+.0f} → <b>{new:+.0f} ms</b>")
        if spread > 40:
            body += "<br>Ha salido bastante irregular: mejor repetirlo."

        def save() -> None:
            self.cfg.audio_offset_ms = new
            self.apply_offsets()
            self.cfg.save()
            self.menus_pop()
            self.toast(f"Retardo del audio: {new:+.0f} ms")
        self.menus.append(Menu("Calibración", [
            Option("Guardar", save),
            Option("Repetir", lambda: (self.menus.pop(), self.start_calibration())),
            Option("Descartar", self.menus_pop),
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
            self.toast("Teclas de siempre")
        return Menu("Teclas", [Option(name, lambda a=action: self.capture_key(a), value=value(action))
                               for action, name, _, _ in ACTIONS]
                    + [Option("Restablecer las de siempre", reset), Option("Volver", self.menu_back)],
                    body=self.keys_body)

    def keys_body(self) -> str:
        if self.capturing:
            mods = " (con Ctrl, Alt o Win)" if self.capturing in GLOBAL_ACTIONS else ""
            return f"Pulsa la tecla{mods} para <b>{ACTION_NAMES[self.capturing]}</b>.<br>Esc o rojo: cancelar"
        return ("Elige una acción y pulsa la tecla nueva; si otra la usaba, se intercambian.<br>"
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
            self.toast(f"«{name}» funciona en todas partes: usa Ctrl, Alt o Win con la tecla "
                       "(si no, esa tecla dejaría de escribir en las demás aplicaciones)", 7)
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
        if self.follow:
            self.watch_aimp(time.perf_counter())

    def song_command(self, cmd: str) -> None:
        """Botones 1, 2 y Home del Wiimote: siguiente, anterior y al azar. Siguiendo a AIMP, se le piden a AIMP
        (al azar, una canción con chart de la biblioteca); si no, en el orden de la biblioteca."""
        if self.follow:
            if cmd == "random":
                songs = [e for albums in self.tree().values() for s in albums.values() for e in s
                         if e.audio != self.aimp_file]
                if songs and self.aimp.play_file(random.choice(songs).audio):
                    self.toast("AIMP: canción al azar")
            else:
                self.aimp.command(CMD_NEXT if cmd == "next" else CMD_PREV)
                self.toast("AIMP: " + ("siguiente" if cmd == "next" else "anterior"))
            return
        if cmd == "random":
            self.play_random()
            return
        songs = [e for albums in self.tree().values() for s in albums.values() for e in s]
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
        elif (ev.kind == "control" and ev.value in ("select", "restart", "start", "pause")) or (
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
                menu.type(ev.value)
                return
            if ev.kind == "control" and ev.value == "restart" and menu.query:  # Retroceso borra
                menu.backspace()
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
            elif ev.value in ("select", "restart"):
                self.menu_back()
            elif ev.value == "pause" and self.menus[0].on_back:
                self.menus[0].on_back()
            elif ev.value == "difficulty":
                self.cycle_difficulty()

    def game_input(self, ev) -> None:
        if ev.kind == "control":
            if ev.value in ("start", "pause"):
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
            if connected:
                self.toast("Guitarra conectada")
            elif self.guitar_connected or self.guitar_connected is None:
                self.toast("Sin guitarra: enciende el Wiimote y se conecta sola (o juega con el teclado)", 6)
            self.guitar_connected = connected
        self.handle_inputs()
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
        active = not self.waiting  # siguiendo a AIMP con una canción sin chart no se juega
        seek = self.player.take_seek()
        if seek is not None and active and now > self.own_seek_until:  # salto hecho en AIMP
            self.results = ""
            self.menus = [m for m in self.menus if m.title != "Fin de la canción"]
            self.new_game()
            self.game.skip_to(seek - self.player.offset_ms + SWITCH_AHEAD_MS)
            self.partial = True
        t = self.player.position_ms(now)
        if self.player.playing and active:
            if self.autoplay:
                self.play_itself(t)
            self.game.update(t)
            if self.best_score and not self.partial and not self.record_toast and self.game.stats.score > self.best_score:
                self.record_toast = True
                self.toast("¡Nuevo récord!")
        for kind, _, ns in self.game.events:
            if kind == "hit":
                for f in ns.note.frets:
                    self.flash_t[f] = now
            else:  # fallo o strum de más: se marca el carril de la nota (o los trastes pulsados)
                self.miss_t = now
                lanes = ns.note.frets if ns is not None else [i for i, h in enumerate(self.held) if h]
                for f in lanes:
                    self.miss_lane_t[f] = now
        self.game.events.clear()
        if active and not self.results and (self.game.finished and t > self.chart.duration_ms - 500
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
        elif self.player.playing and t < 0 and not self.game.stats.hits:
            countdown = -t / 1000
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
            "score": st.score, "streak": st.streak, "mult": st.multiplier, "accuracy": st.accuracy,
            "title": f"AIMP · {self.aimp_title}" if not active else f"{self.chart.artist} – {self.chart.title}",
            "difficulty": DIFF_NAMES[self.difficulty],
            "autoplay": self.autoplay, "best": self.best_score, "partial": self.partial,
            "progress": max(0.0, min(1.0, t / max(1, self.chart.duration_ms))),
            "countdown": countdown, "menu": menu, "calib": calib,
            "menuHint": (LONG_HINT if self.menus[-1].long else MENU_HINT) if menu else "",
            "toast": self.toast_text if now < self.toast_until else (self.waiting if not self.menus else ""),
            "message": self.message, "opacity": self.cfg.opacity, "hwWidth": self.cfg.highway_width,
            "lyricsOn": self.cfg.lyrics, "lyrics": lyrics, "hudSide": self.cfg.hud_side,
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
                    notes += [CALIB_LANE, u, u, 2 if u < -calibration.MAX_DEV_MS / travel else 0, 0, 0, 1]
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
            for f in n.frets:
                notes += [f, max(u, -0.25), u_end, state, int(n.hopo), int(ns.sustaining), len(n.frets)]
            if len(notes) >= 7 * 200:
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
        """Modo automático: toca cada nota a su tiempo y mantiene los trastes hasta la siguiente."""
        g = self.game
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
            record = ("No cuenta para récords (modo automático o empezada a mitad)<br>"
                      + self.record_line())
        else:
            prev = self.records.add_play(self.chart.audio_sha256, self.difficulty, play,
                                         self.chart.title, self.chart.artist)
            self.best_score = max(self.best_score, play.score)
            if prev is None:
                record = self.record_line()
            elif prev.score == 0 and play.score == 0:
                record = f"Primera partida en {DIFF_NAMES[self.difficulty]}"
            elif prev.score == 0:
                record = "<font color='#ffdc00'><b>¡Primer récord!</b></font>"
            else:
                record = (f"<font color='#ffdc00'><b>¡Nuevo récord!</b></font> "
                          f"(+{fmt_int(play.score - prev.score)}; antes {fmt_int(prev.score)})")
        return self.summary(play, record)

    def summary(self, play: Play, record: str) -> str:
        st = self.game.stats
        lines = [f"<b>{DIFF_NAMES[self.difficulty]}: {play.hits}/{play.total} notas ({play.accuracy:.0%})"
                 f"{' · ¡sin fallos!' if play.full_combo else ''}</b>",
                 f"Puntos: {fmt_int(play.score)}",
                 f"Mejor racha: {st.best_streak} · Strums de más: {st.overstrums}", record]
        if len(st.offsets) >= 20:
            offs = sorted(st.offsets)
            med = offs[len(offs) // 2]
            if abs(med) < 3:
                lines.append("Tus strums van justo a tiempo")
            else:
                when = "tarde" if med > 0 else "pronto"
                lines.append(f"Tus strums van de media {abs(med):.0f} ms {when}" +
                             (" (si te pasa siempre, calibra el retardo)" if abs(med) > 25 else ""))
        return "<br>".join(lines)


def fmt_int(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def fmt_date(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if len(iso) >= 10 else iso


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


def tray_icon() -> QIcon:
    """La autopista en pequeño: cinco carriles de colores que se juntan hacia arriba, sobre fondo oscuro."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#151527"))
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    colors = ["#2ecc40", "#ff4136", "#ffdc00", "#1e90ff", "#ff851b"]
    for i, c in enumerate(colors):  # abajo de 8 a 56, arriba de 22 a 42
        x0, x1 = 8 + i * 9.6, 22 + i * 4
        p.setBrush(QColor(c))
        p.drawPolygon(QPolygonF([QPointF(x0 + 1, 54), QPointF(x0 + 8.6, 54), QPointF(x1 + 3.5, 10), QPointF(x1 + 0.5, 10)]))
    p.setBrush(QColor("white"))
    p.drawRect(8, 44, 48, 3)  # la línea de golpeo
    p.end()
    return QIcon(pix)


def make_tray(app: QApplication, session: Session) -> QSystemTrayIcon | None:
    """Icono junto al reloj: un clic muestra u oculta el juego; con el derecho, el menú (y Salir)."""
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    tray = QSystemTrayIcon(tray_icon(), app)
    menu = QMenu()
    toggle = menu.addAction("Mostrar / ocultar", session.toggle_visible)
    menu.addSeparator()
    menu.addAction("Salir", app.quit)

    def refresh() -> None:  # el atajo (se puede cambiar) y lo que suena, al abrir el menú o pasar por encima
        key = win32.combo_label(keymap(session.cfg.keys)["toggle"])
        toggle.setText(f"{'Ocultar' if session.view.isVisible() else 'Mostrar'} ({key})")
        song = f"AIMP: {session.aimp_title}" if session.follow else f"{session.chart.artist} – {session.chart.title}"
        tray.setToolTip(f"Music Hero · {song}")
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
    parser.add_argument("song", type=Path, nargs="?",
                        help="audio (busca su chart en out/charts) o carpeta de chart; sin ella, el selector")
    parser.add_argument("--difficulty", choices=DIFFS,
                        help="por defecto, la última elegida en esa canción o, si no, la de por defecto (Ajustes)")
    parser.add_argument("--speed", type=float, help="velocidad de las notas (1 = normal); el menú la guarda")
    parser.add_argument("--screenshot", type=Path, help="guarda una captura a los N s (--screenshot-at) y sale")
    parser.add_argument("--screenshot-at", type=float, default=8.0)
    parser.add_argument("--screenshot-menu", action="store_true", help="con --screenshot: abre el menú antes")
    parser.add_argument("--autoplay", action="store_true", help="modo automático: el juego toca solo")
    parser.add_argument("--hidden", action="store_true", help="empezar oculto (Ctrl+Alt+H lo muestra)")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    args = parser.parse_args()

    cfg = Config.load()
    if args.speed:
        cfg.note_speed = args.speed
    records = Records()
    if args.song:
        chart = resolve(args.song)
    else:  # el selector, empezando por la última canción jugada
        entries = scan()
        if not entries:
            sys.exit("No hay canciones con chart: genéralas con uv run --project generator generate <carpeta>")
        e = next((e for e in entries if e.sha == records.last), entries[0])
        chart = Chart.load(Path(e.folder))
        chart.audio_file = Path(e.audio)

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
        print("aviso:", e)
    aimp = Aimp()
    session = bridge.session = Session(chart, cfg, args.difficulty, inputs, view, records, aimp)
    session.set_autoplay(args.autoplay)
    session.tray = make_tray(app, session)
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
    topmost.timeout.connect(lambda: view.isVisible() and win32.bring_to_top(int(view.winId())))
    topmost.start(500)
    idle = QTimer()  # oculto no se pinta: el atajo, salir y los botones del Wiimote se atienden aquí
    idle.timeout.connect(lambda: None if view.isVisible() else session.idle_inputs())
    idle.start(50)
    if args.screenshot:
        def shot() -> None:
            app.primaryScreen().grabWindow(0).save(str(args.screenshot))
            app.quit()
        if args.screenshot_menu:
            QTimer.singleShot(int(args.screenshot_at * 1000) - 300, bridge.session.pause)
        QTimer.singleShot(int(args.screenshot_at * 1000), shot)

    if not args.hidden:
        view.show()
        win32.make_click_through(int(view.winId()))
    playing = f"AIMP: {session.aimp_title}" if session.follow else f"{session.chart.artist} - {session.chart.title}"
    keys = {a: win32.combo_label(k) for a, k in keymap(cfg.keys).items()}
    print(f"{playing} ({DIFF_NAMES[session.difficulty]}). + / {keys['pause']}: menú, − / {keys['difficulty']}: "
          f"dificultad, {keys['toggle']} muestra/oculta, {keys['quit']} sale (o el icono junto al reloj).")
    try:
        return app.exec()
    finally:
        inputs.stop()
        session.stop_calibration()
        session.player.close()


if __name__ == "__main__":
    sys.exit(main())
