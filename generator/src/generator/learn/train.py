"""Entrenamiento de OnsetNet con las charts humanas preparadas (learn/data.py).

Uso:
    uv run --project generator python -m generator.learn.train out/dataset/feat --out models/onset.pt

Validación: 5 % de las canciones (fijo por hash). Métrica: F1 de inicios de nota
con ±50 ms, por dificultad, eligiendo el umbral que mejor funciona en validación.
Las canciones de la biblioteca del usuario (data/encore_library.json) se excluyen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from .data import DIFFS, FPS
from .model import N_MELS, OnsetNet

ROOT = Path(__file__).resolve().parents[4]
TOL_FRAMES = int(round(0.05 * FPS))  # ±50 ms


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def is_val(stem: str) -> bool:
    return int(hashlib.md5(stem.encode()).hexdigest(), 16) % 20 == 0


def style_of(meta: dict) -> float:
    """1 = chart de Harmonix (oficial, más sobria), 0 = de la comunidad."""
    return 1.0 if "harmonix" in (meta.get("charter") or "").lower() else 0.0


def with_style(x: np.ndarray, style: float) -> np.ndarray:
    return np.concatenate([x, np.full((len(x), 1), style, np.float32)], axis=1)


class Songs:
    def __init__(self, folder: Path, exclude: set[str]):
        self.items = []
        for lab in sorted(folder.glob("*.npz")):
            feats = lab.with_name(lab.stem + ".feats.npy")
            if not feats.exists():
                continue
            d = np.load(lab)
            meta = json.loads(str(d["meta"]))
            if norm(meta.get("artist")) + "|" + norm(meta.get("name")) in exclude:
                continue
            self.items.append({"stem": lab.stem, "feats": np.load(feats, mmap_mode="r"),
                               "onset": d["onset"], "sustain": d["sustain"], "chord": d["chord"], "meta": meta,
                               "style": style_of(meta)})

    def split(self):
        return [s for s in self.items if not is_val(s["stem"])], [s for s in self.items if is_val(s["stem"])]


def soften(onset: np.ndarray) -> np.ndarray:
    """Objetivo de inicio con los fotogramas vecinos a 0,5: un error de 1 fotograma (12 ms) no es un fallo."""
    out = onset.astype(np.float32)
    out[:, 1:] = np.maximum(out[:, 1:], 0.5 * onset[:, :-1])
    out[:, :-1] = np.maximum(out[:, :-1], 0.5 * onset[:, 1:])
    return out


def batch(songs: list[dict], size: int, length: int, rng: random.Random):
    xs, on, su, ch = [], [], [], []
    for _ in range(size):
        s = rng.choice(songs)
        t = s["feats"].shape[0]
        a = rng.randint(0, max(0, t - length))
        x = with_style(np.asarray(s["feats"][a:a + length], dtype=np.float32), s["style"])
        pad = length - len(x)
        xs.append(np.pad(x, ((0, pad), (0, 0))))
        on.append(np.pad(soften(s["onset"][:, a:a + length]), ((0, 0), (0, pad))))
        su.append(np.pad(s["sustain"][:, a:a + length], ((0, 0), (0, pad))).astype(np.float32))
        ch.append(np.pad(s["chord"][:, a:a + length], ((0, 0), (0, pad))).astype(np.float32))
    to = lambda a: torch.from_numpy(np.stack(a))  # noqa: E731
    return to(xs), to(on).transpose(1, 2), to(su).transpose(1, 2), to(ch).transpose(1, 2)


def loss_fn(logits, on, su, ch):
    lo, ls, lc = logits[..., 0:4], logits[..., 4:8], logits[..., 8:12]
    l_on = F.binary_cross_entropy_with_logits(lo, on, pos_weight=torch.tensor(8.0, device=lo.device))
    l_su = F.binary_cross_entropy_with_logits(ls, su)
    mask = (on >= 1).float()  # el acorde solo importa donde hay nota
    l_ch = (F.binary_cross_entropy_with_logits(lc, ch, reduction="none") * mask).sum() / mask.sum().clamp(min=1)
    return l_on + 0.5 * l_su + 0.3 * l_ch


def peaks(prob: np.ndarray, threshold: float, min_gap: int = 3) -> np.ndarray:
    """Máximos locales por encima del umbral, separados al menos min_gap fotogramas."""
    p = prob
    is_max = (p >= np.roll(p, 1)) & (p >= np.roll(p, -1)) & (p >= threshold)
    idx = np.where(is_max)[0]
    out = []
    for i in idx[np.argsort(-p[idx])]:
        if all(abs(i - j) >= min_gap for j in out):
            out.append(i)
    return np.sort(np.array(out, dtype=int))


def f1(pred: np.ndarray, ref: np.ndarray, tol: int = TOL_FRAMES) -> tuple[int, int, int]:
    """(aciertos, predichas, reales) con emparejamiento voraz dentro de ±tol."""
    if len(pred) == 0 or len(ref) == 0:
        return 0, len(pred), len(ref)
    used = np.zeros(len(ref), bool)
    hits = 0
    for t in pred:
        j = int(np.searchsorted(ref, t))
        best = None
        for k in (j - 1, j):
            if 0 <= k < len(ref) and not used[k] and abs(ref[k] - t) <= tol:
                if best is None or abs(ref[k] - t) < abs(ref[best] - t):
                    best = k
        if best is not None:
            used[best] = True
            hits += 1
    return hits, len(pred), len(ref)


@torch.no_grad()
def predict_song(model: OnsetNet, feats: np.ndarray, device: str, style: float = 1.0,
                 chunk: int = 4096, overlap: int = 512) -> np.ndarray:
    """Probabilidades (T, 12) para una canción entera, por trozos solapados."""
    model.eval()
    if model.n_extra > feats.shape[1] - N_MELS:
        feats = with_style(np.asarray(feats, dtype=np.float32), style)
    t = len(feats)
    out = np.zeros((t, 12), np.float32)
    weight = np.zeros(t, np.float32)
    start = 0
    while start < t:
        end = min(start + chunk, t)
        x = torch.from_numpy(np.asarray(feats[start:end], dtype=np.float32)).unsqueeze(0).to(device)
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=device == "cuda"):
            p = torch.sigmoid(model(x).float())[0].cpu().numpy()
        w = np.ones(end - start, np.float32)
        if start > 0:
            w[:overlap // 2] = 0.0
        if end < t:
            w[-overlap // 2:] = 0.0
        out[start:end] += p * w[:, None]
        weight[start:end] += w
        if end >= t:
            break
        start = end - overlap
    return out / np.maximum(weight, 1e-6)[:, None]


def evaluate(model, songs, device, thresholds=None) -> dict:
    """F1 por dificultad. Si no se dan umbrales, busca el mejor en una rejilla."""
    probs = [predict_song(model, s["feats"], device, s.get("style", 1.0)) for s in songs]
    grid = thresholds or {d: None for d in DIFFS}
    result = {}
    for k, d in enumerate(DIFFS):
        cands = [grid[d]] if grid[d] is not None else [0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
        best = None
        for th in cands:
            h = p_ = r = 0
            for s, pr in zip(songs, probs):
                ref = np.where(s["onset"][k])[0]
                a, b, c = f1(peaks(pr[:, k], th), ref)
                h, p_, r = h + a, p_ + b, r + c
            prec, rec = h / max(1, p_), h / max(1, r)
            score = 2 * prec * rec / max(1e-9, prec + rec)
            if best is None or score > best[0]:
                best = (score, prec, rec, th)
        result[d] = {"f1": best[0], "precision": best[1], "recall": best[2], "threshold": best[3]}
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "models" / "onset.pt")
    ap.add_argument("--steps", type=int, default=30000)
    ap.add_argument("--batch", type=int, default=24)
    ap.add_argument("--length", type=int, default=1536)  # ~18 s
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--eval-every", type=int, default=2000)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    lib = ROOT / "data" / "encore_library.json"
    progress = ROOT / "out" / "dataset" / "library_progress.json"
    found = json.loads(lib.read_text(encoding="utf-8")) if lib.exists() else (
        json.loads(progress.read_text(encoding="utf-8"))["found"] if progress.exists() else [])
    exclude = {norm(m["artist"]) + "|" + norm(m["title"]) for m in found}
    exclude |= {norm(m.get("encore_name", "").split(" - ")[0]) + "|" + norm(m.get("encore_name", "").split(" - ", 1)[-1])
                for m in found}

    songs = Songs(args.data, exclude)
    train, val = songs.split()
    if not val:  # conjuntos diminutos (pruebas): validar con lo que haya
        val = train[:2]
    print(f"{len(train)} canciones de entrenamiento ({sum(s['style'] for s in train):.0f} de Harmonix), "
          f"{len(val)} de validación ({len(exclude)} de la biblioteca excluidas)")
    device = "cuda"
    model = OnsetNet().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, s / 500) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / args.steps))))
    rng = random.Random(0)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    best_f1, t0, running = -1.0, time.time(), []
    for step in range(1, args.steps + 1):
        model.train()
        x, on, su, ch = (a.to(device, non_blocking=True) for a in batch(train, args.batch, args.length, rng))
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            logits = model(x)
        loss = loss_fn(logits.float(), on, su, ch)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        sched.step()
        running.append(loss.item())
        if step % 200 == 0:
            print(f"paso {step}: pérdida {np.mean(running):.4f} ({(time.time() - t0) / step:.2f} s/paso)")
            running = []
        if step % args.eval_every == 0 or step == args.steps:
            res = evaluate(model, val, device)
            mean = float(np.mean([r["f1"] for r in res.values()]))
            print("   validación: " + "  ".join(f"{d} F1 {r['f1']:.3f} (p {r['precision']:.2f} r {r['recall']:.2f} "
                                                 f"umbral {r['threshold']})" for d, r in res.items()))
            if mean > best_f1:
                best_f1 = mean
                torch.save({"model": model.state_dict(), "n_extra": model.n_extra,
                            "thresholds": {d: r["threshold"] for d, r in res.items()},
                            "val": res, "step": step}, args.out)
                print(f"   guardado (F1 medio {mean:.3f}) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
