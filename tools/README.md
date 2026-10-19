# Tools

**English** · [Español](README.es.md)

Command-line helpers for diagnostics, the training dataset and model evaluation. The game itself doesn't need any of them. Run them from the repository root.

## Guitar and AIMP (app environment)

| Script | What it does |
| --- | --- |
| `pair_wiimote.py` | Pairs a Wiimote with Windows without typing the PIN Windows 11 asks for (the game does the same from *Settings → Guitar and keys*). |
| `wii_guitar_monitor.py` | Prints every change the Wii guitar sends (frets, strum, whammy, Start/Select) with the raw bytes. Use it if a button doesn't register. |
| `wii_tilt_monitor.py [seconds]` | Shows the Wiimote's accelerometer while you tilt the guitar up, to check or retune the star power threshold. |
| `measure_aimp_latency.py [seconds] [times]` | Measures how far behind AIMP's reported position the sound you hear is (the game measures it by itself while following AIMP). |

```
uv run --project app python tools/<script>.py
```

Close the game first: it uses the same controller.

## Dataset and models (generator environment, NVIDIA GPU)

| Script | What it does |
| --- | --- |
| `encore_dataset.py catalog \| download \| catalog-extra \| download-extra \| library \| library-download` | Builds the training set from community charts on Chorus Encore (`out/dataset/`). Personal use only. |
| `night_v5.sh` | Overnight run: prepares the data, trains the v5 model and tests it against v4 (~6-7 h). |
| `night_v5d.sh` | Overnight run: fine-tunes v5 with the Demucs guitar (what it gets when generating) and tests it against v5 and v4 (~5-6 h). |
| `eval_model.py <model.pt> <features> [--per-song]` | Tests a model against the human charts of your own library (rhythm F1 and frets). |
| `eval_frets.py <model.pt> <features>` | Compares ways of choosing frets (note by note vs. Viterbi). |
| `eval_vs_human.py <human chart.json> <difficulty> "name=other/chart.json[:difficulty]" ...` | Compares generated charts against a human one for the same song. |

```
uv run --project generator python tools/<script>.py
sh tools/night_v5.sh
sh tools/night_v5d.sh
```

Messages follow the Windows language, or `MUSICHERO_LANG=en` / `es`.
