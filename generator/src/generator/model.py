"""Tipos compartidos por las etapas del generador. Tiempos en ms (int) desde el inicio del audio."""

from dataclasses import dataclass, field

STEMS = ("drums", "bass", "other", "vocals", "guitar", "piano")
# Pistas de las que se pueden sacar notas, por orden de preferencia.
MELODIC_STEMS = ("guitar", "piano", "other", "vocals", "bass")


@dataclass
class SourceNote:
    """Nota transcrita de una pista (antes de pasar a botones)."""

    start_ms: int
    end_ms: int
    pitch: int  # MIDI
    amp: float  # 0..1
    stem: str
    origin: str = "bp"  # "bp": nota de Basic Pitch; "onset": ataque detectado con altura estimada


@dataclass
class ChartNote:
    time_ms: int
    frets: list[int]
    sustain_ms: int = 0
    hopo: bool = False
    # Datos internos, útiles para exportar y para la vista previa; no van al chart.json.
    beat: float = 0.0
    end_beat: float = 0.0
    pitch: int = 0
    stem: str = ""


@dataclass
class SongInfo:
    title: str
    artist: str
    album: str
    duration_ms: int
    audio_sha256: str
    audio_path: str


@dataclass
class Section:
    """Tramo (compás) y la pista elegida para sacar sus notas."""

    start_beat: float
    end_beat: float
    stem: str
    scores: dict[str, float] = field(default_factory=dict)
    energy: float = 0.0  # 0 tranquilo .. 1 enérgico (decide cuántas notas caben)
