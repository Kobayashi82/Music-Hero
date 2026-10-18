"""F1 de inicios (y botones, si el modelo los tiene) de un modelo OnsetNet sobre canciones preparadas que no ha visto.

Uso:
    uv run --project generator python tools/eval_model.py models/onset_v1.pt out/dataset/feat_library [--per-song]

La carpeta sale de `python -m generator.learn.data <sng> <carpeta>` (p. ej. las charts
humanas de la biblioteca, out/encore/). Muestra el F1 con los umbrales guardados en
el modelo, por separado para charts de Harmonix y de la comunidad (cada una con su
estilo), y con --per-song el F1 de cada canción en Experto.
"""
import sys
from pathlib import Path

import numpy as np

from generator.i18n import t
from generator.learn.infer import load
from generator.learn.train import Songs, evaluate, f1, peaks, predict_song


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    model_path, folder = Path(sys.argv[1]), Path(sys.argv[2])
    model, thresholds = load(model_path, "cuda")
    songs = Songs(folder, exclude=set()).items
    print(t("{n} canciones; umbrales del modelo {th}", n=len(songs), th=thresholds))
    for name, group in (("Harmonix", [s for s in songs if s["style"]]),
                        (t("comunidad"), [s for s in songs if not s["style"]])):
        if not group:
            continue
        res = evaluate(model, group, "cuda", thresholds)
        print(t("{name} ({n} canciones):", name=name, n=len(group)))
        for d, r in res.items():
            frets = ("   " + t("botones: exactos {exact:.0%}, dirección {dir:.0%}, acordes {pred:.0%} (humanas {ref:.0%})",
                                exact=r["fret_exact"], dir=r["fret_dir"], pred=r["chords_pred"], ref=r["chords_ref"])
                     ) if "fret_exact" in r else ""
            print(f"  {d:<7} F1 {r['f1']:.3f}  " + t("(precisión {p:.2f}, recall {r:.2f})", p=r["precision"],
                                                       r=r["recall"]) + frets)
    if "--per-song" not in sys.argv:
        return 0
    print("\n" + t("Experto por canción (notas del modelo / humanas):"))
    rows = []
    for s in songs:
        pr = predict_song(model, s["feats"], "cuda", s["style"])
        h, p, r = f1(peaks(pr[:, 0], thresholds["expert"]), np.where(s["onset"][0])[0])
        rows.append((2 * h / max(1, p + r), p, r, f"{s['meta'].get('artist')} - {s['meta'].get('name')} ({s['meta'].get('charter')})"))
    for sc, p, r, name in sorted(rows):
        print(f"  {sc:.2f}  {p:5d}/{r:<5d} {name}")
    print("\n" + t("mediana por canción: {m:.3f}", m=np.median([r[0] for r in rows])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
