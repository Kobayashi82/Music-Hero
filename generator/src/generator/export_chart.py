"""Salidas: chart.json (shared/chart_schema.json v2) y carpeta Clone Hero/YARG (notes.chart + song.ini)."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .model import ChartNote, Section, SongInfo
from .rhythm import TempoMap

SCHEMA_VERSION = 2  # v2: frases de star power por dificultad
RESOLUTION = 192
CH_HOPO_TICKS = 65  # umbral de HOPO natural de Clone Hero/YARG a 192 ticks por pulso
CH_TRACKS = {"expert": "ExpertSingle", "hard": "HardSingle", "medium": "MediumSingle", "easy": "EasySingle"}
STEM_NAMES = {"guitar": "Guitarra", "piano": "Piano", "other": "Otros", "vocals": "Voz", "bass": "Bajo"}


def _tempo_changes(tempo: TempoMap, sections: list[Section]) -> list[dict]:
    """Un cambio de tempo por compás cuando el tempo medio varía más de un 1 %."""
    out: list[dict] = []
    for sec in sections:
        bpm = 60000 * (sec.end_beat - sec.start_beat) / max(
            1, tempo.beat_to_ms(sec.end_beat) - tempo.beat_to_ms(sec.start_beat)
        )
        if out and abs(bpm - out[-1]["bpm"]) / out[-1]["bpm"] < 0.01:
            continue
        out.append({"time_ms": tempo.beat_to_ms(sec.start_beat), "bpm": round(bpm, 2)})
    if not out or out[0]["time_ms"] != 0:
        out.insert(0, {"time_ms": 0, "bpm": round(tempo.bpm_at(0), 2)})
    out[0]["time_signature"] = [tempo.beats_per_measure, 4]
    return out


def chart_json(song: SongInfo, tempo: TempoMap, difficulties: dict[str, list[ChartNote]],
               sections: list[Section], generator_version: str, source_stem: str = "guitar",
               star_power: dict[str, list[tuple[int, int]]] | None = None) -> dict:
    """star_power: frases (inicio, fin) en ms por dificultad (las de la chart humana); sin ellas, el juego las pone."""
    downbeats = set(tempo.downbeats_ms)
    beats = []
    for b in tempo.beats_ms:
        entry = {"time_ms": int(b)}
        if any(abs(b - d) <= 30 for d in downbeats):
            entry["downbeat"] = True
        beats.append(entry)

    def note_dict(n: ChartNote) -> dict:
        d = {"time_ms": n.time_ms, "frets": sorted(n.frets)}
        if n.sustain_ms:
            d["sustain_ms"] = n.sustain_ms
        if n.hopo:
            d["hopo"] = True
        return d

    def track(diff: str, notes: list[ChartNote]) -> dict:
        d = {"notes": [note_dict(n) for n in notes]}
        if (star_power or {}).get(diff):
            d["star_power"] = [{"time_ms": a, "length_ms": b - a} for a, b in star_power[diff]]
        return d

    song_d = {"title": song.title, "artist": song.artist, "duration_ms": song.duration_ms,
              "audio_sha256": song.audio_sha256, "audio_file": song.audio_path}
    if song.album:
        song_d["album"] = song.album
    return {
        "schema_version": SCHEMA_VERSION,
        "song": song_d,
        "generator": {"version": generator_version,
                      "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "source_stem": source_stem},
        "tempo": _tempo_changes(tempo, sections),
        "beats": beats,
        "difficulties": {k: track(k, v) for k, v in difficulties.items()},
    }


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _tick(beat: float) -> int:
    return int(round(beat * RESOLUTION))


def _natural_hopo(n: ChartNote, prev: ChartNote | None) -> bool:
    if prev is None or len(n.frets) != 1:
        return False
    return _tick(n.beat) - _tick(prev.beat) <= CH_HOPO_TICKS and n.frets[0] not in prev.frets


def write_clonehero(folder: Path, song: SongInfo, tempo: TempoMap, difficulties: dict[str, list[ChartNote]],
                    sections: list[Section], copy_audio: bool = True,
                    star_power: dict[str, list[tuple[int, int]]] | None = None) -> Path:
    """Carpeta lista para YARG/Clone Hero/Moonscraper: notes.chart, song.ini y song.<ext>."""
    folder.mkdir(parents=True, exist_ok=True)
    audio = Path(song.audio_path)
    music = f"song{audio.suffix.lower()}"

    def q(s: str) -> str:
        return s.replace('"', "'")

    lines = ["[Song]", "{",
             f'  Name = "{q(song.title)}"', f'  Artist = "{q(song.artist)}"', f'  Album = "{q(song.album)}"',
             '  Charter = "Music Hero"', "  Offset = 0", f"  Resolution = {RESOLUTION}",
             '  Player2 = bass', "  Difficulty = 0", "  PreviewStart = 0", "  PreviewEnd = 0",
             '  Genre = ""', '  MediaType = "cd"', f'  MusicStream = "{music}"', "}"]

    lines += ["[SyncTrack]", "{", f"  0 = TS {tempo.beats_per_measure}"]
    last_value = None
    for i in range(len(tempo.anchor_beats) - 1):
        value = int(round(tempo.bpm_at(tempo.anchor_beats[i]) * 1000))
        if value != last_value:
            lines.append(f"  {_tick(tempo.anchor_beats[i])} = B {value}")
            last_value = value
    lines.append("}")

    lines += ["[Events]", "{"]
    last_stem = None
    for sec in sections:
        if sec.stem and sec.stem != last_stem:
            lines.append(f'  {_tick(sec.start_beat)} = E "section {STEM_NAMES.get(sec.stem, sec.stem)}"')
            last_stem = sec.stem
    lines.append("}")

    for diff, notes in difficulties.items():
        lines += [f"[{CH_TRACKS[diff]}]", "{"]
        prev = None
        events = []
        for a, b in (star_power or {}).get(diff, []):  # frases de star power: "S 2 <duración>"
            ta = _tick(tempo.ms_to_beat(a))
            events.append((ta, f"  {ta} = S 2 {max(1, _tick(tempo.ms_to_beat(b)) - ta)}"))
        for n in notes:
            t = _tick(n.beat)
            while events and events[0][0] <= t:
                lines.append(events.pop(0)[1])
            sus = max(0, _tick(n.end_beat) - t) if n.sustain_ms else 0
            for f in sorted(n.frets):
                lines.append(f"  {t} = N {f} {sus}")
            if n.hopo != _natural_hopo(n, prev):
                lines.append(f"  {t} = N 5 0")  # invierte el HOPO natural
            prev = n
        lines += [e for _, e in events]
        lines.append("}")

    (folder / "notes.chart").write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    ini = ["[song]", f"name = {song.title}", f"artist = {song.artist}", f"album = {song.album}",
           "charter = Music Hero", f"song_length = {song.duration_ms}", "diff_guitar = -1",
           "delay = 0", "preview_start_time = 0"]
    (folder / "song.ini").write_text("\n".join(ini) + "\n", encoding="utf-8")
    if copy_audio and not (folder / music).exists():
        shutil.copy2(audio, folder / music)
    return folder
