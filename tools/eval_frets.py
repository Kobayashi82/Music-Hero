"""Botones nota a nota (lo más probable) frente a Viterbi con transiciones humanas (generator.learn.frets).

Sobre los inicios de las charts humanas (aísla los botones del ritmo): combinación exacta, dirección
entre notas seguidas (por el botón más bajo), acordes y cuántas veces repite botón.

Uso:
    uv run --project generator python tools/eval_frets.py models/onset_v4.pt out/dataset/feat_library
"""
import sys
from pathlib import Path

import numpy as np

from generator.learn.data import FPS
from generator.learn.frets import fret_emissions, load_transitions, viterbi
from generator.learn.infer import load
from generator.learn.model import combo_frets
from generator.learn.train import DIFFS, Songs, predict_song

# (peso del modelo, fuerza de las transiciones)
SETTINGS = [(w, b) for b in (1.0, 0.6, 0.35) for w in (1.0, 2.0)]
N_M = 10


def metrics(pred: np.ndarray, ref: np.ndarray) -> np.ndarray:
    low = lambda c: np.array([combo_frets(int(x))[0] for x in c])  # noqa: E731
    dp, dr = np.sign(np.diff(low(pred))), np.sign(np.diff(low(ref)))
    chord = lambda c: np.array([len(combo_frets(int(x))) > 1 for x in c])  # noqa: E731
    moves = dr != 0
    return np.array([(pred == ref).sum(), (dp == dr).sum(), len(dr), chord(pred).sum(), chord(ref).sum(),
                     (np.diff(pred) == 0).sum(), (np.diff(ref) == 0).sum(), len(ref),
                     (dp[moves] == dr[moves]).sum(), moves.sum()], float)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    model, _ = load(Path(sys.argv[1]), "cuda")
    songs = Songs(Path(sys.argv[2]), exclude=set()).items
    trans = load_transitions()
    probs = [predict_song(model, s["feats"], "cuda", s["style"]) for s in songs]
    print(f"{len(songs)} canciones")
    for k, d in enumerate(DIFFS):
        rows = {"nota a nota": np.zeros(N_M)} | {f"v {w:g}/{b:g}": np.zeros(N_M) for w, b in SETTINGS}
        for s, pr in zip(songs, probs):
            frames, ref = s["frets"][k]
            if len(frames) < 2:
                continue
            e = fret_emissions(pr, k, frames)
            rows["nota a nota"] += metrics(e.argmax(axis=1), ref)
            for w, b in SETTINGS:
                rows[f"v {w:g}/{b:g}"] += metrics(viterbi(e, frames / FPS * 1000, b * trans[k], w), ref)
        print(f"{d}:")
        for name, m in rows.items():
            ex, dr, nd, cp, cr, rp, rr, n, mv, nm = m
            print(f"  {name:<12} exactos {ex / n:5.1%}  dirección {dr / nd:5.1%}  sube/baja {mv / nm:5.1%}  acordes {cp / n:5.1%} (humanas {cr / n:.1%})"
                  f"  repite {rp / nd:5.1%} (humanas {rr / nd:.1%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
