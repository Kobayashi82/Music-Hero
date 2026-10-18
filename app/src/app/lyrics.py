"""Letra sincronizada (lyrics.json junto a chart.json, shared/lyrics_schema.json): qué línea se ve en cada
momento y hasta dónde va iluminada."""

from __future__ import annotations

import bisect
import json
from dataclasses import dataclass
from pathlib import Path

SHOW_BEFORE_MS = 1500  # una línea aparece (sin iluminar) esto antes de empezar a cantarse
HOLD_MS = 1200  # y se queda esto después de acabar, si no viene otra
NEXT_WITHIN_MS = 10000  # la siguiente se enseña debajo si empieza dentro de esto


@dataclass
class Line:
    start_ms: int
    end_ms: int
    text: str
    words: list[tuple[int, int, int, int]]  # (inicio ms, fin ms, primer carácter, carácter tras la palabra)

    def fill(self, t: float) -> float:
        """Caracteres de text ya cantados en t (con decimales: la palabra que suena se va llenando)."""
        done = 0.0
        for start, end, a, b in self.words:
            if t < start:
                break
            if t >= end:
                done = b
            else:
                done = a + (b - a) * (t - start) / max(1, end - start)
                break
        return done


def _line(d: dict) -> Line:
    joined = "".join(w["text"] for w in d["words"])
    pos = -(len(joined) - len(joined.lstrip()))  # text es joined sin los espacios del principio
    words = []
    for w in d["words"]:
        lead = len(w["text"]) - len(w["text"].lstrip())
        words.append((int(w["start_ms"]), int(w["end_ms"]), max(0, pos + lead), max(0, pos + len(w["text"]))))
        pos += len(w["text"])
    text = joined.strip()
    words = [(s, e, min(a, len(text)), min(b, len(text))) for s, e, a, b in words]
    return Line(int(d["start_ms"]), int(d["end_ms"]), text, words)


class Lyrics:
    def __init__(self, lines: list[Line], source: str = ""):
        self.lines = sorted(lines, key=lambda line: line.start_ms)
        self.starts = [line.start_ms for line in self.lines]
        self.source = source

    @classmethod
    def load(cls, folder: Path, audio_sha256: str) -> Lyrics | None:
        """La letra de la chart de esa carpeta, o None si no hay, está rota, no tiene líneas o es de otro audio."""
        try:
            d = json.loads((folder / "lyrics.json").read_text(encoding="utf-8"))
            if d.get("audio_sha256") != audio_sha256:
                return None
            lines = [_line(x) for x in d.get("lines", []) if x.get("words")]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return cls(lines, d.get("source", "")) if lines else None

    def view(self, t: float) -> dict:
        """{current, fill, next} en el momento t (ms). current vacío: nada que enseñar ahora."""
        i = bisect.bisect_right(self.starts, t + SHOW_BEFORE_MS) - 1  # la última que ya se enseña
        if i >= 0:
            line = self.lines[i]
            nxt = self.lines[i + 1] if i + 1 < len(self.lines) else None
            if t > line.end_ms + HOLD_MS and (nxt is None or nxt.start_ms - SHOW_BEFORE_MS > t):
                i = -1  # pausa larga: ya se fue y la siguiente aún no
            elif i > 0 and t < line.start_ms and t <= self.lines[i - 1].end_ms:
                i -= 1  # la anterior aún se está cantando: no se le quita el sitio
        if i < 0:
            return {"current": "", "fill": 0.0, "next": ""}
        line = self.lines[i]
        nxt = self.lines[i + 1] if i + 1 < len(self.lines) else None
        show_next = nxt is not None and nxt.start_ms - max(t, line.end_ms) <= NEXT_WITHIN_MS
        return {"current": line.text, "fill": line.fill(t), "next": nxt.text if show_next else ""}
