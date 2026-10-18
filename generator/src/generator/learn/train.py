"""Entrenamiento de OnsetNet con las charts humanas preparadas (learn/data.py).

Uso:
    uv run --project generator python -m generator.learn.train out/dataset/feat --out models/onset.pt
    uv run --project generator python -m generator.learn.train out/dataset/feat5 --guitar --frets --out models/onset_v5.pt

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

from ..i18n import t
from .data import DIFFS, FPS
from .model import N_COMBOS, N_MELS, OnsetNet, combo_frets

ROOT = Path(__file__).resolve().parents[4]
TOL_FRAMES = int(round(0.05 * FPS))  # ±50 ms
FRET_WEIGHT = 0.5


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
                               "style": style_of(meta),
                               # dificultades sin notas = el charter no las hizo, no "aquí no se toca"
                               "has": d["onset"].sum(axis=1) > 0,
                               "frets": [fret_labels(d[f"notes_{x}"]) for x in DIFFS]})

    def split(self):
        return [s for s in self.items if not is_val(s["stem"])], [s for s in self.items if is_val(s["stem"])]


def fret_labels(notes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(fotogramas, combinación de botones) de cada nota; notes = notes_<dif> de data.py."""
    frames = np.round(notes[:, 0] / 1000 * FPS).astype(np.int64)
    combos = (notes[:, 2:7] > 0.5).astype(np.int64) @ (1 << np.arange(5))
    keep = combos > 0  # notas al aire: no hay botón que aprender
    return frames[keep], combos[keep]


def fret_target(frets: list[tuple[np.ndarray, np.ndarray]], a: int, length: int) -> np.ndarray:
    """(length, 4) con la combinación en el inicio de cada nota y sus vecinos (±1 fotograma), -100 = no cuenta."""
    out = np.full((length, len(frets)), -100, np.int64)
    for k, (frames, combos) in enumerate(frets):
        i, j = np.searchsorted(frames, [a - 1, a + length + 1])
        f, c = frames[i:j] - a, combos[i:j]
        for off in (-1, 1, 0):  # el propio inicio, al final, manda sobre el vecino de otra nota
            g = f + off
            ok = (g >= 0) & (g < length)
            out[g[ok], k] = c[ok]
    return out


def soften(onset: np.ndarray) -> np.ndarray:
    """Objetivo de inicio con los fotogramas vecinos a 0,5: un error de 1 fotograma (12 ms) no es un fallo."""
    out = onset.astype(np.float32)
    out[:, 1:] = np.maximum(out[:, 1:], 0.5 * onset[:, :-1])
    out[:, :-1] = np.maximum(out[:, :-1], 0.5 * onset[:, 1:])
    return out


def batch(songs: list[dict], size: int, length: int, rng: random.Random):
    xs, on, su, ch, has, fr = [], [], [], [], [], []
    for _ in range(size):
        s = rng.choice(songs)
        has.append(s["has"].astype(np.float32))
        t = s["feats"].shape[0]
        a = rng.randint(0, max(0, t - length))
        x = with_style(np.asarray(s["feats"][a:a + length], dtype=np.float32), s["style"])
        pad = length - len(x)
        xs.append(np.pad(x, ((0, pad), (0, 0))))
        on.append(np.pad(soften(s["onset"][:, a:a + length]), ((0, 0), (0, pad))))
        su.append(np.pad(s["sustain"][:, a:a + length], ((0, 0), (0, pad))).astype(np.float32))
        ch.append(np.pad(s["chord"][:, a:a + length], ((0, 0), (0, pad))).astype(np.float32))
        fr.append(fret_target(s["frets"], a, length))
    to = lambda a: torch.from_numpy(np.stack(a))  # noqa: E731
    return (to(xs), to(on).transpose(1, 2), to(su).transpose(1, 2), to(ch).transpose(1, 2),
            to(has)[:, None, :], to(fr))


def loss_fn(logits, on, su, ch, has, fr=None):
    """has (B, 1, 4): 0 en las dificultades que la chart no tiene, que no cuentan.
    fr (B, T, 4): combinación de botones en los inicios (-100 = no cuenta); solo si el modelo tiene botones."""
    lo, ls, lc = logits[..., 0:4], logits[..., 4:8], logits[..., 8:12]
    bce = lambda x, y, **kw: F.binary_cross_entropy_with_logits(x, y, reduction="none", **kw)  # noqa: E731
    frames = (has * torch.ones_like(on)).sum().clamp(min=1)
    l_on = (bce(lo, on, pos_weight=torch.tensor(8.0, device=lo.device)) * has).sum() / frames
    l_su = (bce(ls, su) * has).sum() / frames
    mask = (on >= 1).float() * has  # el acorde solo importa donde hay nota
    l_ch = (bce(lc, ch) * mask).sum() / mask.sum().clamp(min=1)
    total = l_on + 0.5 * l_su + 0.3 * l_ch
    if fr is not None and logits.shape[-1] > 12:
        lf = logits[..., 12:].reshape(-1, N_COMBOS)
        if (fr >= 0).any():
            total = total + FRET_WEIGHT * F.cross_entropy(lf, fr.reshape(-1), ignore_index=-100)
    return total


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
    """Probabilidades (T, 12) para una canción entera, por trozos solapados; con botones, (T, 12 + 4 x 32):
    detrás, la probabilidad de cada combinación de botones por dificultad (suma 1, la 0 nunca)."""
    model.eval()
    if feats.shape[1] < model.n_in:  # falta la columna de estilo
        feats = with_style(np.asarray(feats, dtype=np.float32), style)
    t = len(feats)
    out = np.zeros((t, model.n_out), np.float32)
    weight = np.zeros(t, np.float32)
    start = 0
    while start < t:
        end = min(start + chunk, t)
        x = torch.from_numpy(np.asarray(feats[start:end], dtype=np.float32)).unsqueeze(0).to(device)
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=device == "cuda"):
            logits = model(x).float()[0]
        p = torch.sigmoid(logits[:, :12])
        if model.frets:
            lf = logits[:, 12:].reshape(-1, 4, N_COMBOS)
            lf[..., 0] = -1e9  # sin botón no existe en el formato
            p = torch.cat([p, torch.softmax(lf, dim=-1).reshape(len(p), -1)], dim=1)
        p = p.cpu().numpy()
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
                if not s["onset"][k].any():  # dificultad que la chart no tiene
                    continue
                ref = np.where(s["onset"][k])[0]
                a, b, c = f1(peaks(pr[:, k], th), ref)
                h, p_, r = h + a, p_ + b, r + c
            prec, rec = h / max(1, p_), h / max(1, r)
            score = 2 * prec * rec / max(1e-9, prec + rec)
            if best is None or score > best[0]:
                best = (score, prec, rec, th)
        result[d] = {"f1": best[0], "precision": best[1], "recall": best[2], "threshold": best[3]}
        if model.frets:
            result[d].update(fret_metrics(songs, probs, k))
    return result


def fret_combo_at(prob: np.ndarray, k: int, frame: int) -> int:
    """Combinación más probable en la dificultad k alrededor de un inicio (±1 fotograma)."""
    p = prob[max(0, frame - 1):frame + 2, 12 + k * N_COMBOS:12 + (k + 1) * N_COMBOS].sum(axis=0)
    return int(np.argmax(p))


def fret_metrics(songs: list[dict], probs: list[np.ndarray], k: int) -> dict:
    """Botones sobre los inicios humanos (aísla los botones del ritmo): combinación exacta, dirección
    entre notas seguidas (sube / baja / igual, por el botón más bajo) y proporción de acordes."""
    exact = same_dir = n_dir = chords_p = chords_r = n = 0
    for s, pr in zip(songs, probs):
        frames, ref = s["frets"][k]
        if not len(frames):
            continue
        pred = np.array([fret_combo_at(pr, k, int(f)) for f in frames])
        exact += int((pred == ref).sum())
        low = lambda c: np.array([combo_frets(int(x))[0] for x in c])  # noqa: E731
        dp, dr = np.sign(np.diff(low(pred))), np.sign(np.diff(low(ref)))
        same_dir += int((dp == dr).sum())
        n_dir += len(dr)
        chords_p += sum(len(combo_frets(int(x))) > 1 for x in pred)
        chords_r += sum(len(combo_frets(int(x))) > 1 for x in ref)
        n += len(ref)
    return {"fret_exact": exact / max(1, n), "fret_dir": same_dir / max(1, n_dir),
            "chords_pred": chords_p / max(1, n), "chords_ref": chords_r / max(1, n)}


def init_from(model: OnsetNet, path: Path) -> None:
    """Copia los pesos de otro modelo; si este tiene más salidas (botones), las 12 primeras se copian
    y el resto empieza de cero."""
    src = torch.load(path, map_location="cpu")["model"]
    own = model.state_dict()
    for name, w in src.items():
        if own[name].shape == w.shape:
            own[name].copy_(w)
        else:  # última capa: las salidas nuevas van detrás
            own[name][:w.shape[0]].copy_(w)
    print(t("pesos iniciales de {name}", name=path.name))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "models" / "onset.pt")
    ap.add_argument("--steps", type=int, default=30000)
    ap.add_argument("--batch", type=int, default=24)
    ap.add_argument("--length", type=int, default=1536)  # ~18 s
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--eval-every", type=int, default=2000)
    ap.add_argument("--frets", action="store_true", help=t("aprender también los botones de cada nota"))
    ap.add_argument("--init", type=Path, help=t("empezar desde los pesos de otro modelo (p. ej. models/onset_v3.pt)"))
    ap.add_argument("--guitar", action="store_true",
                    help=t("entrada con la pista de guitarra y su CQT (datos de learn.data --guitar)"))
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
    print(t("{train} canciones de entrenamiento ({harmonix:.0f} de Harmonix), {val} de validación ({excluded} de la "
            "biblioteca excluidas)", train=len(train), harmonix=sum(s["style"] for s in train), val=len(val),
            excluded=len(exclude)))
    device = "cuda"
    model = OnsetNet(frets=args.frets, guitar=args.guitar).to(device)
    if args.init:
        init_from(model, args.init)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, s / 500) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / args.steps))))
    rng = random.Random(0)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    best_f1, t0, running = -1.0, time.time(), []
    skipped = in_a_row = 0
    for step in range(1, args.steps + 1):
        model.train()
        x, on, su, ch, has, fr = (a.to(device, non_blocking=True) for a in batch(train, args.batch, args.length, rng))
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            logits = model(x)
        loss = loss_fn(logits.float(), on, su, ch, has, fr)
        opt.zero_grad(set_to_none=True)
        ok = bool(torch.isfinite(loss))
        if ok:
            loss.backward()
            ok = bool(torch.isfinite(torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)))
        # Un lote con NaN (bf16) estropearía todos los pesos (v3 murió así en el paso ~9500): se salta.
        if ok:
            opt.step()
            running.append(loss.item())
            in_a_row = 0
        else:
            opt.zero_grad(set_to_none=True)
            skipped += 1
            in_a_row += 1
            if in_a_row >= 50:
                print(t("paso {step}: 50 lotes seguidos con NaN, se para (el mejor modelo ya está en {out})",
                        step=step, out=args.out))
                return 1
        sched.step()
        if step % 200 == 0:
            extra = ", " + t("{n} lotes saltados por NaN", n=skipped) if skipped else ""
            print(t("paso {step}: pérdida {loss:.4f} ({secs:.2f} s/paso{extra})", step=step,
                    loss=np.mean(running) if running else float("nan"), secs=(time.time() - t0) / step, extra=extra))
            running = []
        if step % args.eval_every == 0 or step == args.steps:
            res = evaluate(model, val, device)
            # con botones se guarda el que mejor combina ritmo y botones
            mean = float(np.mean([r["f1"] + r.get("fret_exact", 0.0) for r in res.values()]))
            print("   " + t("validación:") + " " + "  ".join(
                f"{d} F1 {r['f1']:.3f} (p {r['precision']:.2f} r {r['recall']:.2f} "
                + t("umbral {th}", th=r["threshold"]) + ")" for d, r in res.items()))
            if args.frets:
                print("   " + t("botones:") + "    " + "  ".join(
                    f"{d} " + t("exactos {exact:.0%} dirección {dir:.0%} acordes {pred:.0%}/{ref:.0%}",
                                exact=r["fret_exact"], dir=r["fret_dir"], pred=r["chords_pred"], ref=r["chords_ref"])
                    for d, r in res.items()))
            if mean > best_f1:
                best_f1 = mean
                torch.save({"model": model.state_dict(), "n_extra": model.n_extra, "frets": model.frets,
                            "guitar": model.guitar,
                            "thresholds": {d: r["threshold"] for d, r in res.items()},
                            "val": res, "step": step}, args.out)
                print("   " + t("guardado (puntuación {score:.3f}) -> {out}", score=mean, out=args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
