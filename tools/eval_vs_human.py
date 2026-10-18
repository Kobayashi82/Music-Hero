"""Compara charts candidatas con una chart humana sincronizada (mismo audio): ritmo y botones.

Uso:
    uv run --project generator python tools/eval_vs_human.py out/charts/<canción>/chart.json expert "mi chart=otra/chart.json:expert"

Argumentos: human_chart.json dificultad nombre=archivo.json[:dificultad] ...
  - human_chart.json: chart.json del generador con la chart humana (--human)
  - candidatas: chart.json (difficulties.<d>.notes) o json de Tab Hero ({d: [{timestamp_ms, frets}]})
"""
import json
import sys

import numpy as np

from generator.i18n import t

TOL = 60


def load(path: str, diff: str) -> list[tuple[float, tuple]]:
    d = json.load(open(path, encoding="utf-8"))
    if "difficulties" in d:
        return [(n["time_ms"], tuple(n["frets"])) for n in d["difficulties"][diff]["notes"]]
    return [(n["timestamp_ms"], tuple(f for f in n["frets"] if f < 5)) for n in d[diff]]


def compare(ref, cand, offset=0.0):
    rt = np.array([t for t, _ in ref]); ct = np.array([t + offset for t, _ in cand])
    used = set(); hits = []
    for i, t in enumerate(ct):
        j = int(np.clip(np.searchsorted(rt, t), 1, len(rt) - 1))
        k = j - 1 if abs(rt[j - 1] - t) <= abs(rt[j] - t) else j
        if abs(rt[k] - t) <= TOL and k not in used:
            used.add(k); hits.append((i, k))
    p, r = len(hits) / max(1, len(ct)), len(hits) / max(1, len(rt))
    f = 2 * p * r / (p + r) if p + r else 0
    # botones: dirección del movimiento entre notas acertadas consecutivas (sube/baja/igual)
    same_dir = []
    for (i1, k1), (i2, k2) in zip(hits, hits[1:]):
        dc = np.sign(min(cand[i2][1] or (0,)) - min(cand[i1][1] or (0,)))
        dr = np.sign(min(ref[k2][1]) - min(ref[k1][1]))
        same_dir.append(dc == dr)
    chords_c = np.mean([len(c[1]) > 1 for c in cand]) if cand else 0
    return f, r, p, float(np.mean(same_dir)) if same_dir else 0, chords_c


ref_path, diff = sys.argv[1], sys.argv[2]
ref = load(ref_path, diff)
dur = (ref[-1][0] - ref[0][0]) / 1000
print(t("referencia humana ({diff}): {n} notas, {nps:.2f}/s, acordes {ch:.0%}", diff=diff, n=len(ref),
        nps=len(ref) / dur, ch=np.mean([len(f) > 1 for _, f in ref])))
print(f"{t('candidata'):<26} {t('notas'):>6} {'F1':>5} {'recall':>7} {t('precis.'):>8} {t('dirección'):>10} "
      f"{t('acordes'):>8}")
for arg in sys.argv[3:]:
    name, spec = arg.split("=", 1)
    path, _, d = spec.rpartition(":")
    if d not in ("expert", "hard", "medium", "easy"):
        path, d = spec, ""
    cand = sorted(load(path, d or diff))
    best = max((compare(ref, cand, o) + (o,) for o in range(-300, 301, 10)), key=lambda x: x[0])
    f, r, p, dirm, ch, o = best
    print(f"{name:<26} {len(cand):6} {f:5.2f} {r:7.0%} {p:8.0%} {dirm:10.0%} {ch:8.0%}   "
          + t("(desfase {ms} ms)", ms=o))
