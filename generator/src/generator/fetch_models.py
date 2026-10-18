"""fetch_models: baja los modelos que usa el motor (Demucs, Beat This!, Whisper) adonde los buscan sus librerías,
con progreso en líneas JSON y reanudando lo que quedó a medias. Lo lanza la app al instalar el motor (fase 7).

    python -m generator.fetch_models [--check]

Las carpetas salen del entorno (como las leen las librerías): TORCH_HOME para Demucs y Beat This!,
XDG_CACHE_HOME para Whisper. --check solo dice qué falta.

Avisos (stdout): {"event": "plan", "files": [{"name", "size"}...]}, {"event": "progress", "name", "done", "total"},
{"event": "file_done", "name"}, {"event": "done"} o {"event": "error", "message"}.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .i18n import t

CHUNK = 1 << 20
USER_AGENT = "MusicHero/0.1 (https://github.com/Kobayashi82/Music-Hero)"


@dataclass
class ModelFile:
    name: str
    url: str
    path: Path
    sha256_prefix: str = ""  # lo que se comprueba al acabar (Demucs: 8 primeros; Whisper: entero)


def model_files() -> list[ModelFile]:
    import torch.hub
    import whisper
    from beat_this.inference import CHECKPOINT_URL
    from demucs.pretrained import REMOTE_ROOT, _parse_remote_files

    from .lyrics import WHISPER_MODEL
    from .separate import MODEL as DEMUCS_MODEL

    hub = Path(torch.hub.get_dir()) / "checkpoints"
    out = []
    remote = _parse_remote_files(REMOTE_ROOT / "files.txt")
    sigs = [line.strip(" -'\"[]") for line in (REMOTE_ROOT / f"{DEMUCS_MODEL}.yaml").read_text().splitlines()
            if line.startswith("models:")]
    for sig in sigs[0].replace("models:", "").strip(" []").replace("'", "").split(","):
        url = remote[sig.strip()]
        name = url.rsplit("/", 1)[1]
        out.append(ModelFile(f"Demucs {DEMUCS_MODEL}", url, hub / name, name.rsplit("-", 1)[1].split(".")[0]))
    out.append(ModelFile("Beat This!", f"{CHECKPOINT_URL}/final0.ckpt", hub / "beat_this-final0.ckpt"))
    url = whisper._MODELS[WHISPER_MODEL]
    root = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache")) / "whisper"
    out.append(ModelFile(f"Whisper {WHISPER_MODEL}", url, root / url.rsplit("/", 1)[1], url.split("/")[-2]))
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def is_ready(m: ModelFile) -> bool:
    return m.path.is_file() and (not m.sha256_prefix or _sha256(m.path).startswith(m.sha256_prefix))


def remote_size(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers.get("Content-Length") or 0)
    except OSError:
        return 0


def download(m: ModelFile, emit) -> None:
    """A m.path pasando por .part: si se corta, la próxima vez sigue donde iba (Range)."""
    m.path.parent.mkdir(parents=True, exist_ok=True)
    part = m.path.with_name(m.path.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": USER_AGENT} | ({"Range": f"bytes={have}-"} if have else {})
    with urllib.request.urlopen(urllib.request.Request(m.url, headers=headers), timeout=60) as r:
        if have and r.status != 206:  # el servidor no reanuda: desde el principio
            have = 0
        total = have + int(r.headers.get("Content-Length") or 0)
        with open(part, "ab" if have else "wb") as f:
            done, last = have, -1
            while chunk := r.read(CHUNK):
                f.write(chunk)
                done += len(chunk)
                pct = done * 100 // max(1, total)
                if pct != last:
                    emit({"event": "progress", "name": m.name, "done": done, "total": total})
                    last = pct
    if m.sha256_prefix and not _sha256(part).startswith(m.sha256_prefix):
        part.unlink()
        raise OSError(t("{name}: el archivo bajado no es el que debería (hash); se bajará otra vez", name=m.name))
    os.replace(part, m.path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help=t("solo decir qué falta"))
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    def emit(d: dict) -> None:
        print(json.dumps(d, ensure_ascii=False), flush=True)

    try:
        missing = [m for m in model_files() if not is_ready(m)]
        emit({"event": "plan", "files": [{"name": m.name, "size": remote_size(m.url)} for m in missing]})
        if args.check:
            return 0 if not missing else 1
        for m in missing:
            download(m, emit)
            emit({"event": "file_done", "name": m.name})
    except Exception as e:  # noqa: BLE001 - sin red, disco lleno...: la app lo enseña y se puede repetir
        emit({"event": "error", "message": f"{type(e).__name__}: {e}"})
        return 1
    emit({"event": "done"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
