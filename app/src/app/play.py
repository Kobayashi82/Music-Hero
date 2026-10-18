"""play [canción.mp3 | carpeta de chart] -> juega en el overlay, con el reproductor propio (fase 3).

Uso:
    uv run --project app play            (abre el selector de canciones, en la última que jugaste)
    uv run --project app play "D:/Programas/Multimedia/Musicas/Queen/Greatest Hits II/Queen - Hammer to Fall.mp3"
    uv run --project app play "out/charts/Queen - Hammer to Fall" --difficulty hard

Controles: ver app/inputs.py (A S D F G + flechas, o la guitarra de Wii). + o Espacio abren el menú
(dificultad, ajustes, calibración); − o Tab cambian de dificultad sin parar. Ctrl+Alt+H muestra/oculta;
Ctrl+Alt+Q sale. Ajustes en %APPDATA%/MusicHero/config.json (se guardan solos desde el menú).
"""

from __future__ import annotations

import argparse
import bisect
import random
import signal
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QColor, QGuiApplication, QSurfaceFormat
from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface

from . import calibration, win32
from .chart import DIFF_NAMES, DIFFS, Chart, find_chart
from .config import Config
from .gameplay import HIT, MISSED, SKIPPED, Game
from .inputs import Inputs
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
LONG_HINT = MENU_HINT + " · Amarillo / Azul: saltar 10"
POSITIONS = {"left": "Izquierda", "center": "Centro", "right": "Derecha"}
MENU_REPEAT_S = (0.35, 0.08, 0.035)  # strum mantenido en un menú: espera, repetición y, pasados 2 s, más rápido
SIDES = {"left": "Izquierda", "right": "Derecha"}


class Session(QObject):
    def __init__(self, chart: Chart, cfg: Config, difficulty: str | None, inputs: Inputs, view: QQuickView,
                 records: Records | None = None):
        super().__init__()
        self.cfg, self.inputs, self.view = cfg, inputs, view
        self.records = records or Records()
        self.player: Player | None = None
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
        self.strum_hold: tuple[int, float, float] | None = None  # strum mantenido en un menú: (dirección, desde, siguiente)
        self.message = "; ".join(inputs.errors)
        self.autoplay = False
        self.partial = False  # la partida no cuenta para récords (automático o empezada a mitad)
        self.record_toast = False  # ya se avisó de que se ha superado el récord en esta partida
        self.load_song(chart, difficulty)

    def load_song(self, chart: Chart, difficulty: str | None = None) -> None:
        """Pone esta canción (al empezar o desde el selector): su dificultad es la pedida, la última elegida
        en ella o la de por defecto."""
        self.stop_calibration()
        player = Player(chart.audio_file, self.cfg.audio_offset_ms, LEAD_IN_MS, self.cfg.volume)
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
        self.player.seek(-LEAD_IN_MS)
        self.new_game()
        self.results, self.resume_at = "", None
        self.player.play()

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
            self.pause()
            self.inputs.set_game_keys(False)
            self.view.hide()
        else:
            self.view.show()
            win32.make_click_through(int(self.view.winId()))
            self.inputs.set_game_keys(True)

    def toast(self, text: str, seconds: float = TOAST_S) -> None:
        self.toast_text, self.toast_until = text, time.perf_counter() + seconds

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
            self.load_song(chart)
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
        return Menu("Pausa", [
            Option("Continuar", self.resume),
            Option("Cambiar canción", self.open_selector),
            Option("Canción al azar", self.play_random),
            Option("Buscar canción", self.open_search),
            self.difficulty_option(),
            self.autoplay_option(),
            Option("Reiniciar", self.restart),
            Option("Ajustes", lambda: self.menus.append(self.settings_menu())),
            Option("Calibrar el retardo", self.start_calibration),
            Option("Salir", QGuiApplication.quit),
        ], body=lambda: f"{self.chart.artist} – {self.chart.title}<br>{self.record_line()}", on_back=self.resume)

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
            Option("Salir", QGuiApplication.quit),
        ], body=lambda: self.results)

    def settings_menu(self) -> Menu:
        cfg = self.cfg

        def num(name: str, step: float, lo: float, hi: float, after=None):
            def set_(v: float) -> None:
                setattr(cfg, name, v)
                if after:
                    after()
                cfg.save()
            return stepper(lambda: getattr(cfg, name), set_, step, lo, hi)

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
            Option("Retardo del audio", value=lambda: f"{cfg.audio_offset_ms:+.0f} ms",
                   change=num("audio_offset_ms", 5, -300, 500,
                              lambda: setattr(self.player, "offset_ms", cfg.audio_offset_ms))),
            Option("Retardo de la imagen", value=lambda: f"{cfg.video_offset_ms:+.0f} ms",
                   change=num("video_offset_ms", 5, -200, 300)),
            Option("Opacidad del fondo", value=lambda: pct(cfg.opacity), change=num("opacity", 0.05, 0.2, 1.0)),
            Option("Ancho de la autopista", value=lambda: f"{cfg.highway_width} px",
                   change=num("highway_width", 40, 320, 1200, self.place)),
            Option("Posición", value=lambda: POSITIONS.get(cfg.position, cfg.position),
                   change=cycler(list(POSITIONS), lambda: cfg.position, set_position)),
            Option("Marcador", value=lambda: SIDES.get(cfg.hud_side, cfg.hud_side),
                   change=cycler(list(SIDES), lambda: cfg.hud_side,
                                 lambda v: (setattr(cfg, "hud_side", v), cfg.save()))),
            Option("Letra", value=lambda: "Sí" if cfg.lyrics else "No",
                   change=cycler([False, True], lambda: cfg.lyrics,
                                 lambda v: (setattr(cfg, "lyrics", v), cfg.save()))),
            Option("Volver", self.menu_back),
        ], body="Elige una opción para cambiarla con el strum; se guarda sola.")

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
            self.player.offset_ms = new
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

    # ---------- entrada ----------

    def handle_inputs(self) -> None:
        for ev in self.inputs.drain():
            if ev.kind == "fret":
                self.held[ev.value] = ev.down
            if ev.kind == "control" and ev.value in ("quit", "toggle"):
                QGuiApplication.quit() if ev.value == "quit" else self.toggle_visible()
            elif self.calib:
                self.calib_input(ev)
            elif self.menus:
                self.menu_input(ev)
            else:
                self.game_input(ev)
        if not self.player.playing or self.menus:  # trastes al día para cuando se siga jugando
            self.game.held = {i for i, h in enumerate(self.held) if h}

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
        if not self.player.playing:
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
        if self.strum_hold and (not self.menus or self.calib):
            self.strum_hold = None
        if self.strum_hold and now >= self.strum_hold[2]:  # strum mantenido: sigue desplazando
            d, since, _ = self.strum_hold
            self.menus[-1].move(d)
            self.strum_hold = (d, since, now + MENU_REPEAT_S[1 if now - since < 2 else 2])
        if self.calib and self.calib.finished:
            self.finish_calibration()
        t = self.player.position_ms(now)
        if self.player.playing:
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
        if not self.results and (self.game.finished and t > self.chart.duration_ms - 500 or self.player.finished):
            self.results = self.finish_song()
            self.player.pause()
            self.menus = [self.results_menu()]

        travel = TRAVEL_MS / max(0.3, self.cfg.note_speed)
        lyrics = {}
        if self.calib:
            notes, beats = self.calib_notes(now, travel)
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
            "notes": notes, "beats": beats, "held": self.held if not self.menus else [False] * 5,  # en los menús no se encienden los botones "time": now,
            "flash": [max(0.0, 1 - (now - ft) / 0.3) for ft in self.flash_t],
            "burn": [i in burn for i in range(5)],
            "missFlash": max(0.0, 1 - (now - self.miss_t) / 0.35),
            "missLane": [max(0.0, 1 - (now - mt) / 0.4) for mt in self.miss_lane_t],
            "score": st.score, "streak": st.streak, "mult": st.multiplier, "accuracy": st.accuracy,
            "title": f"{self.chart.artist} – {self.chart.title}", "difficulty": DIFF_NAMES[self.difficulty],
            "autoplay": self.autoplay, "best": self.best_score, "partial": self.partial,
            "progress": max(0.0, min(1.0, t / max(1, self.chart.duration_ms))),
            "countdown": countdown, "menu": menu, "calib": calib,
            "menuHint": (LONG_HINT if self.menus[-1].long else MENU_HINT) if menu else "",
            "toast": self.toast_text if now < self.toast_until else "",
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


def place_view(view: QQuickView, cfg: Config) -> None:
    geo = QGuiApplication.primaryScreen().availableGeometry()
    w = min(geo.width(), cfg.highway_width + SIDE_MARGIN)
    x = {"left": geo.x(), "right": geo.x() + geo.width() - w}.get(cfg.position, geo.x() + (geo.width() - w) // 2)
    view.setGeometry(x, geo.y(), w, geo.height())


def make_view(cfg: Config, bridge: Bridge) -> QQuickView:
    view = QQuickView()
    view.setFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                  | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
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
    app = QGuiApplication(sys.argv)
    bridge = Bridge()
    view = make_view(cfg, bridge)

    inputs = Inputs()
    inputs.start()
    inputs.set_game_keys(True)
    for e in inputs.errors:
        print("aviso:", e)
    bridge.session = Session(chart, cfg, args.difficulty, inputs, view, records)
    bridge.session.set_autoplay(args.autoplay)
    if not args.song:
        bridge.session.open_selector()

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer()  # deja que Python atienda Ctrl+C
    keepalive.start(200)
    keepalive.timeout.connect(lambda: None)
    topmost = QTimer()
    topmost.timeout.connect(lambda: view.isVisible() and win32.bring_to_top(int(view.winId())))
    topmost.start(500)
    if args.screenshot:
        def shot() -> None:
            app.primaryScreen().grabWindow(0).save(str(args.screenshot))
            app.quit()
        if args.screenshot_menu:
            QTimer.singleShot(int(args.screenshot_at * 1000) - 300, bridge.session.pause)
        QTimer.singleShot(int(args.screenshot_at * 1000), shot)

    view.show()
    win32.make_click_through(int(view.winId()))
    print(f"{chart.artist} - {chart.title} ({DIFF_NAMES[bridge.session.difficulty]}). "
          "+ / Espacio: menú, − / Tab: dificultad, Ctrl+Alt+H oculta, Ctrl+Alt+Q sale.")
    try:
        return app.exec()
    finally:
        inputs.stop()
        bridge.session.stop_calibration()
        bridge.session.player.close()


if __name__ == "__main__":
    sys.exit(main())
