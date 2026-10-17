"""Notas de cada pista con Basic Pitch (ONNX en CUDA) + ataques detectados en la propia pista.

Con guitarra distorsionada Basic Pitch se deja muchas notas: el ritmo importa más
que la altura exacta, así que los ataques que detecta librosa y Basic Pitch no
cubre se añaden como notas, con la altura más activa del modelo en ese momento.
"""

import logging
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .audio import load_mono
from .model import SourceNote

# onnxruntime-gpu usa las DLL de CUDA que trae torch: importarlo antes.
import torch  # noqa: F401,E402
import onnxruntime as ort  # noqa: E402

if hasattr(ort, "preload_dlls"):
    ort.preload_dlls()

_level = logging.getLogger().level
logging.getLogger().setLevel(logging.ERROR)  # Basic Pitch avisa de cada backend que falta
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from basic_pitch import ICASSP_2022_MODEL_PATH  # noqa: E402
    from basic_pitch.constants import AUDIO_SAMPLE_RATE, FFT_HOP  # noqa: E402
    from basic_pitch.inference import Model, run_inference  # noqa: E402
    from basic_pitch.note_creation import model_frames_to_time, model_output_to_notes  # noqa: E402
logging.getLogger().setLevel(_level)

MIDI_OFFSET = 21  # columna 0 de la salida de Basic Pitch = La0 (MIDI 21)


@dataclass(frozen=True)
class StemParams:
    onset_threshold: float
    frame_threshold: float
    min_note_ms: float
    min_freq: float | None
    max_freq: float | None
    melodia: bool = True
    add_onsets: bool = True
    onset_delta: float = 0.25  # sensibilidad del detector de ataques (más bajo = más ataques)


PARAMS = {
    "guitar": StemParams(0.35, 0.25, 60, 70, 1500, onset_delta=0.2),
    "bass": StemParams(0.40, 0.30, 80, 30, 400),
    "piano": StemParams(0.45, 0.30, 60, None, None),
    "other": StemParams(0.45, 0.30, 70, 60, 2000),
    "vocals": StemParams(0.50, 0.30, 100, 70, 1100, add_onsets=False),
}


@dataclass
class Transcription:
    stem: str
    notes: list[SourceNote]
    frame_times_ms: np.ndarray  # tiempos de los frames del modelo (~86 por segundo)
    rms_db: np.ndarray  # energía de la pista en esos mismos frames
    active_db: float  # umbral por encima del cual la pista "suena"


_model: Model | None = None


def get_model() -> Model:
    """Basic Pitch carga el ONNX solo en CPU; cambiamos la sesión por una con CUDA."""
    global _model
    if _model is None:
        _model = Model(ICASSP_2022_MODEL_PATH)
        if str(ICASSP_2022_MODEL_PATH).endswith(".onnx"):
            _model.model = ort.InferenceSession(
                str(ICASSP_2022_MODEL_PATH), providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
            )
    return _model


def _rms_db(y: np.ndarray, n_frames: int) -> np.ndarray:
    hop = FFT_HOP
    pad = np.pad(y, (hop, hop * 2))
    frames = np.lib.stride_tricks.sliding_window_view(pad, hop * 2)[::hop][:n_frames]
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1) + 1e-12)
    out = 20 * np.log10(rms)
    if len(out) < n_frames:
        out = np.pad(out, (0, n_frames - len(out)), constant_values=-120)
    return out


def transcribe(stem_path: Path, stem: str) -> Transcription:
    import librosa

    p = PARAMS[stem]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        output = run_inference(stem_path, get_model())
        min_len = int(round(p.min_note_ms / 1000 * AUDIO_SAMPLE_RATE / FFT_HOP))
        _, events = model_output_to_notes(
            output,
            onset_thresh=p.onset_threshold,
            frame_thresh=p.frame_threshold,
            min_note_len=max(1, min_len),
            min_freq=p.min_freq,
            max_freq=p.max_freq,
            include_pitch_bends=False,
            melodia_trick=p.melodia,
        )

    activation = output["note"]  # (frames, 88)
    times_ms = model_frames_to_time(activation.shape[0]) * 1000
    y = load_mono(stem_path, AUDIO_SAMPLE_RATE)
    rms_db = _rms_db(y, activation.shape[0])
    loud = np.percentile(rms_db, 95)
    active_db = max(loud - 30, -55)

    notes = [
        SourceNote(int(round(s * 1000)), int(round(e * 1000)), int(pitch), float(amp), stem, "bp")
        for s, e, pitch, amp, _ in events
    ]

    if p.add_onsets:
        notes += _onset_notes(y, notes, activation, times_ms, rms_db, active_db, p, stem, librosa)

    notes.sort(key=lambda n: (n.start_ms, n.pitch))
    return Transcription(stem, notes, times_ms, rms_db, active_db)


def detect_onsets(y: np.ndarray, delta: float, librosa) -> np.ndarray:
    """Ataques en ms. La fuerza de ataque se normaliza por ventanas de ~6 s: con la
    normalización global de librosa, un tramo fuerte esconde los ataques de los versos."""
    import scipy.ndimage as nd

    env = librosa.onset.onset_strength(y=y, sr=AUDIO_SAMPLE_RATE, hop_length=FFT_HOP)
    scale = nd.percentile_filter(env, 95, size=int(AUDIO_SAMPLE_RATE / FFT_HOP * 6)) + 1e-6
    peaks = librosa.util.peak_pick(env / scale, pre_max=3, post_max=3, pre_avg=12, post_avg=12, delta=delta, wait=5)
    # Además, un mínimo global: en pistas con mucha reverb la normalización local
    # convierte cualquier ondulación en "ataque".
    peaks = peaks[env[peaks] >= np.percentile(env, 75)]
    return librosa.frames_to_time(peaks, sr=AUDIO_SAMPLE_RATE, hop_length=FFT_HOP) * 1000


def _onset_notes(y, notes, activation, times_ms, rms_db, active_db, p: StemParams, stem: str, librosa):
    """Ataques de la pista que Basic Pitch no ha convertido en nota."""
    onsets_ms = detect_onsets(y, p.onset_delta, librosa)
    if len(onsets_ms) == 0:
        return []
    by_start = sorted(notes, key=lambda n: n.start_ms)
    known = np.array([n.start_ms for n in by_start]) if notes else np.array([-10**9])
    lo = 0 if p.min_freq is None else max(0, int(round(librosa.hz_to_midi(p.min_freq))) - MIDI_OFFSET)
    hi = 88 if p.max_freq is None else min(88, int(round(librosa.hz_to_midi(p.max_freq))) - MIDI_OFFSET + 1)

    extra = []
    for t in onsets_ms:
        i = int(np.searchsorted(known, t))
        near = min(abs(t - known[j]) for j in (i - 1, i) if 0 <= j < len(known))
        if near < 50:
            continue
        f = int(np.searchsorted(times_ms, t))
        if f >= len(times_ms) or rms_db[f] < active_db:
            continue
        win = activation[f:f + 9, lo:hi]  # ~100 ms tras el ataque
        if win.size == 0:
            continue
        col = int(win.max(axis=0).argmax())
        act = float(win[:, col].max())
        if act >= 0.12:
            pitch = lo + col + MIDI_OFFSET
            k = f  # duración: hasta que la activación de esa altura cae
            while k < len(times_ms) - 1 and activation[k, lo + col] > p.frame_threshold * 0.8 and k - f < 400:
                k += 1
            end = max(times_ms[k], t + 80)
        else:
            # Sin altura clara (palm mute, distorsión): repite la nota anterior más cercana.
            prev = by_start[i - 1] if i > 0 and notes else None
            if prev is None or t - prev.start_ms > 2000:
                continue
            pitch, end = prev.pitch, t + 80
        # El ataque es fiable aunque la altura no lo sea: amplitud mínima para no filtrarlo luego.
        extra.append(SourceNote(int(round(t)), int(round(end)), pitch, max(act, 0.3), stem, "onset"))
    return extra
