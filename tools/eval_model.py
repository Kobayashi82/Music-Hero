"""F1 de inicios de un modelo OnsetNet sobre canciones preparadas que no ha visto.

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

from generator.learn.infer import load
from generator.learn.train import Songs, evaluate, f1, peaks, predict_song


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    model_path, folder = Path(sys.argv[1]), Path(sys.argv[2])
    model, thresholds = load(model_path, "cuda")
    songs = Songs(folder, exclude=set()).items
    print(f"{len(songs)} canciones; umbrales del modelo {thresholds}")
    for name, group in (("Harmonix", [s for s in songs if s["style"]]), ("comunidad", [s for s in songs if not s["style"]])):
        if not group:
            continue
        res = evaluate(model, group, "cuda", thresholds)
        print(f"{name} ({len(group)} canciones):")
        for d, r in res.items():
            print(f"  {d:<7} F1 {r['f1']:.3f}  (precisión {r['precision']:.2f}, recall {r['recall']:.2f})")
    if "--per-song" not in sys.argv:
        return 0
    print("\nExperto por canción (notas del modelo / humanas):")
    rows = []
    for s in songs:
        pr = predict_song(model, s["feats"], "cuda", s["style"])
        h, p, r = f1(peaks(pr[:, 0], thresholds["expert"]), np.where(s["onset"][0])[0])
        rows.append((2 * h / max(1, p + r), p, r, f"{s['meta'].get('artist')} - {s['meta'].get('name')} ({s['meta'].get('charter')})"))
    for sc, p, r, name in sorted(rows):
        print(f"  {sc:.2f}  {p:5d}/{r:<5d} {name}")
    print(f"\nmediana por canción: {np.median([r[0] for r in rows]):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
