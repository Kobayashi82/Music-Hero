"""Usa OnsetNet sobre una canción: inicios, duraciones y acordes por dificultad."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from ..audio import load_mono
from .data import DIFFS, FPS, SR, features
from .model import OnsetNet
from .train import peaks, predict_song

MIN_SUSTAIN_S = 0.2  # sostenidos más cortos que esto son notas normales


@dataclass
class ModelNote:
    start_ms: int
    end_ms: int  # = start_ms + 100 si no es sostenida
    chord: float  # probabilidad de acorde
    strength: float  # probabilidad del inicio


def load(path: Path, device: str = "cuda") -> tuple[OnsetNet, dict]:
    ck = torch.load(path, map_location=device)
    model = OnsetNet(n_extra=ck.get("n_extra", 2)).to(device)  # v1 sin entrada de estilo
    model.load_state_dict(ck["model"])
    model.eval()
    return model, ck["thresholds"]


def predict(audio: Path, model_path: Path, device: str = "cuda", style: float = 1.0) -> dict[str, list[ModelNote]]:
    """style: 1 = como Harmonix (sobria), 0 = como la comunidad (más cargada); los modelos v1 lo ignoran."""
    model, thresholds = load(model_path, device)
    y = load_mono(audio, SR)
    peak = np.abs(y).max()
    feats = features(y / peak if peak > 0 else y, device)
    probs = predict_song(model, feats, device, style)
    out = {}
    for k, d in enumerate(DIFFS):
        on = peaks(probs[:, k], thresholds[d])
        notes = []
        for i, f in enumerate(on):
            nxt = on[i + 1] if i + 1 < len(on) else len(probs)
            end = f + 1
            while end < nxt - 2 and probs[end, 4 + k] > 0.5:
                end += 1
            start_ms = int(round(f / FPS * 1000))
            end_ms = int(round(end / FPS * 1000)) if (end - f) / FPS >= MIN_SUSTAIN_S else start_ms + 100
            notes.append(ModelNote(start_ms, end_ms, float(probs[f, 8 + k]), float(probs[f, k])))
        out[d] = notes
    return out
