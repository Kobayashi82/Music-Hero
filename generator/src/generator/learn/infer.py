"""Usa OnsetNet sobre una canción: inicios, duraciones y acordes por dificultad."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from ..audio import load_mono
from ..i18n import t
from .data import DIFFS, FPS, SR, features
from .frets import fret_emissions, load_transitions, viterbi
from .model import OnsetNet, combo_frets
from .train import fret_combo_at, peaks, predict_song

MIN_SUSTAIN_S = 0.2  # sostenidos más cortos que esto son notas normales
# Con 0,5 el modelo marca un 14 % de fotogramas como sostenidos frente al 36 % de las
# charts humanas (biblioteca, v1); con 0,25 la proporción es parecida (38 %).
SUSTAIN_THRESHOLD = 0.25
# Notas por segundo como mínimo (p1 de las charts humanas: 0,84 / 0,65 / 0,45 / 0,33). En pistas
# ambientales el modelo apenas pasa del umbral y la chart sale vacía: se baja el umbral hasta llegar.
MIN_NPS = {"expert": 0.8, "hard": 0.6, "medium": 0.4, "easy": 0.3}
# Botones por secuencia (frets.py): (peso del modelo, fuerza de las transiciones). Solo en Experto: en el
# examen (92 charts, tools/eval_frets.py) sube/baja acierta 41,7 % frente a 37,5 % nota a nota; en Difícil
# apenas cambia y en Medio y Fácil empeora (repite botón de más).
VITERBI = {"expert": (1.0, 0.6)}
LOWER_THRESHOLDS = (0.5, 0.4, 0.3, 0.2, 0.1, 0.05)


def onsets_with_min(prob: np.ndarray, threshold: float, min_count: int) -> tuple[np.ndarray, float]:
    """Inicios con el umbral del modelo; si salen menos de min_count, con umbrales más bajos."""
    on = peaks(prob, threshold)
    for th in LOWER_THRESHOLDS:
        if len(on) >= min_count:
            break
        if th < threshold:
            on, threshold = peaks(prob, th), th
    return on, threshold


@dataclass
class ModelNote:
    start_ms: int
    end_ms: int  # = start_ms + 100 si no es sostenida
    chord: float  # probabilidad de acorde
    strength: float  # probabilidad del inicio
    frets: list[int] | None = None  # botones (modelos con botones, v4+)


def load(path: Path, device: str = "cuda") -> tuple[OnsetNet, dict]:
    ck = torch.load(path, map_location=device)
    model = OnsetNet(n_extra=ck.get("n_extra", 2), frets=ck.get("frets", False),  # v1 sin estilo
                     guitar=ck.get("guitar", False)).to(device)
    model.load_state_dict(ck["model"])
    model.eval()
    return model, ck["thresholds"]


def predict(audio: Path, model_path: Path, device: str = "cuda", style: float = 1.0,
            guitar: Path | None = None) -> dict[str, list[ModelNote]]:
    """style: 1 = como Harmonix (sobria), 0 = como la comunidad (más cargada); los modelos v1 lo ignoran.
    guitar: pista de guitarra de Demucs (stems/guitar.flac), la necesitan los modelos con guitarra (v5+)."""
    model, thresholds = load(model_path, device)
    y = load_mono(audio, SR)
    peak = np.abs(y).max()
    scale = 1 / peak if peak > 0 else 1.0
    g = None
    if model.guitar:
        if guitar is None:
            raise ValueError(t("{name} necesita la pista de guitarra (stems/guitar.flac)", name=model_path.name))
        g = load_mono(guitar, SR) * scale  # con la escala de la mezcla, como al entrenar
    feats = features(y * scale, device, g)
    probs = predict_song(model, feats, device, style)
    out = {}
    seconds = len(probs) / FPS
    for k, d in enumerate(DIFFS):
        on, th = onsets_with_min(probs[:, k], thresholds[d], int(MIN_NPS[d] * seconds))
        if th != thresholds[d]:
            print(f"    {d}: " + t("pocas notas con el umbral {old}, bajado a {new} ({n} notas)", old=thresholds[d],
                                    new=th, n=len(on)), flush=True)
        combos = None
        if model.frets:
            trans = load_transitions() if d in VITERBI else None
            if trans is not None and len(on):
                w, b = VITERBI[d]
                combos = viterbi(fret_emissions(probs, k, on), on / FPS * 1000, b * trans[k], w)
            else:
                combos = [fret_combo_at(probs, k, int(f)) for f in on]
        notes = []
        for i, f in enumerate(on):
            nxt = on[i + 1] if i + 1 < len(on) else len(probs)
            end = f + 1
            while end < nxt - 2 and probs[end, 4 + k] > SUSTAIN_THRESHOLD:
                end += 1
            start_ms = int(round(f / FPS * 1000))
            end_ms = int(round(end / FPS * 1000)) if (end - f) / FPS >= MIN_SUSTAIN_S else start_ms + 100
            frets = combo_frets(int(combos[i])) if combos is not None else None
            notes.append(ModelNote(start_ms, end_ms, float(probs[f, 8 + k]), float(probs[f, k]), frets))
        out[d] = notes
    return out
