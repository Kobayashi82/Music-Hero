"""Botones por secuencia: Viterbi entre lo que dice el modelo de cada nota y cómo se mueven las charts humanas.

El modelo (v4+) da, en el inicio de cada nota, la probabilidad de cada una de las 32 combinaciones de
botones, pero nota a nota: no sabe qué botón llevaba la anterior, y la forma sale a saltos. Aquí se elige
la secuencia entera que maximiza

    peso * log P_modelo(combinación) + log P_humanas(combinación | anterior, tiempo entre las dos)

con las transiciones contadas en las charts humanas del dataset, por dificultad y por tramo de tiempo
entre notas (cerca: pasos pequeños; lejos: cualquier cosa).

Contar las transiciones (una vez, CPU, ~1 min):
    uv run --project generator python -m generator.learn.frets out/dataset/feat
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from .data import DIFFS
from .model import N_COMBOS

GAP_EDGES_MS = (90, 160, 260, 450)  # 5 tramos de tiempo entre notas
TRANSITIONS = Path(__file__).with_name("fret_transitions.npy")
SMOOTH = 0.5  # cuentas añadidas a cada transición (las que no se han visto nunca no son imposibles)


def gap_bucket(gap_ms):
    return np.searchsorted(GAP_EDGES_MS, gap_ms, side="right")


def combos_of(notes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(tiempos ms, combinación) de notes_<dif> de data.py, sin notas al aire."""
    c = (notes[:, 2:7] > 0.5).astype(np.int64) @ (1 << np.arange(5))
    keep = c > 0
    return notes[keep, 0], c[keep]


def count_transitions(folder: Path) -> np.ndarray:
    """(4 dificultades, tramos, 32, 32) cuentas de anterior -> siguiente."""
    counts = np.zeros((len(DIFFS), len(GAP_EDGES_MS) + 1, N_COMBOS, N_COMBOS), np.float64)
    files = sorted(folder.glob("*.npz"))
    for i, f in enumerate(files):
        d = np.load(f)
        for k, diff in enumerate(DIFFS):
            t, c = combos_of(d[f"notes_{diff}"])
            if len(c) < 2:
                continue
            np.add.at(counts[k], (gap_bucket(np.diff(t)), c[:-1], c[1:]), 1)
        if (i + 1) % 500 == 0:
            print(f"{i + 1}/{len(files)}", flush=True)
    return counts


def log_transitions(counts: np.ndarray) -> np.ndarray:
    """log P(siguiente | anterior, tramo); la combinación 0 (ninguno) imposible."""
    c = counts + SMOOTH
    c[..., 0] = 0
    c[..., 0, :] = SMOOTH  # filas de la 0: nunca se usan, que no den NaN
    with np.errstate(divide="ignore"):
        return np.log(c / c.sum(axis=-1, keepdims=True))


_cache: dict[str, np.ndarray] = {}


def load_transitions() -> np.ndarray | None:
    if "t" not in _cache:
        if not TRANSITIONS.exists():
            return None
        _cache["t"] = log_transitions(np.load(TRANSITIONS))
    return _cache["t"]


def fret_emissions(prob: np.ndarray, k: int, frames: np.ndarray) -> np.ndarray:
    """(N, 32) probabilidad de cada combinación en cada inicio de la dificultad k (±1 fotograma, como
    train.fret_combo_at); prob = salida de train.predict_song de un modelo con botones."""
    cols = slice(12 + k * N_COMBOS, 12 + (k + 1) * N_COMBOS)
    e = np.stack([prob[max(0, int(f) - 1):int(f) + 2, cols].sum(axis=0) for f in frames])
    return e / e.sum(axis=1, keepdims=True)


def viterbi(emis: np.ndarray, times_ms: np.ndarray, log_trans: np.ndarray, weight: float) -> np.ndarray:
    """emis (N, 32) probabilidades del modelo por nota; log_trans (tramos, 32, 32) de una dificultad.
    Devuelve la combinación de cada nota."""
    n = len(emis)
    if n == 0:
        return np.zeros(0, np.int64)
    with np.errstate(divide="ignore"):
        le = weight * np.log(np.maximum(emis, 1e-12))
    le[:, 0] = -np.inf
    buckets = gap_bucket(np.diff(times_ms))
    score = le[0].copy()
    back = np.zeros((n, N_COMBOS), np.int64)
    for i in range(1, n):
        cand = score[:, None] + log_trans[buckets[i - 1]]  # (anterior, siguiente)
        back[i] = cand.argmax(axis=0)
        score = cand[back[i], np.arange(N_COMBOS)] + le[i]
    out = np.zeros(n, np.int64)
    out[-1] = int(score.argmax())
    for i in range(n - 1, 0, -1):
        out[i - 1] = back[i, out[i]]
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    counts = count_transitions(Path(sys.argv[1]))
    np.save(TRANSITIONS, counts.astype(np.float32))
    for k, diff in enumerate(DIFFS):
        print(f"{diff}: {int(counts[k].sum())} transiciones")
    print(f"-> {TRANSITIONS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
