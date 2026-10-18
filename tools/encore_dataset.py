"""Charts humanas de Chorus Encore: catálogo, descarga y búsqueda de la biblioteca propia.

Uso:
    uv run --project generator python tools/encore_dataset.py catalog      # elige qué charts bajar
    uv run --project generator python tools/encore_dataset.py download     # baja los .sng (reanudable)
    uv run --project generator python tools/encore_dataset.py catalog-extra   # segunda tanda (oficiales + teclado + más géneros)
    uv run --project generator python tools/encore_dataset.py download-extra  # la baja a la misma carpeta sng/
    uv run --project generator python tools/encore_dataset.py library      # busca las canciones de la biblioteca
    uv run --project generator python tools/encore_dataset.py library-download  # (re)baja sus charts a out/encore/

Salidas:
    out/dataset/catalog.json        charts elegidas para entrenar (metadatos de Encore)
    out/dataset/catalog_extra.json  segunda tanda, sin repetir canciones de la primera
    out/dataset/sng/<md5>.sng       paquetes descargados
    data/encore_library.json        canciones de la biblioteca con chart humana (no se usan para entrenar)

Encore es un servicio gratuito sin API documentada: mismas llamadas que Bridge,
de una en una y con pausas. Las descargas (files.enchor.us, Cloudflare) pueden
estar bloqueadas desde España; con VPN funcionan.
"""

import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from generator.i18n import t

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "dataset"
CATALOG = OUT / "catalog.json"
CATALOG_EXTRA = OUT / "catalog_extra.json"
SNG_DIR = OUT / "sng"
LIBRARY_JSON = ROOT / "data" / "encore_library.json"
MUSIC_DIR = Path("D:/Programas/Multimedia/Musicas")
API = "https://api.enchor.us"
FILES = "https://files.enchor.us"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MusicHero/0.1"}  # Cloudflare rechaza "Python-urllib"
BUDGET_BYTES = 130 * 1024**3  # tope de sng/: 30 GB de la primera tanda + 100 GB más (permitido por el usuario)

# Cupos por consulta: (campo, valor, máximo de charts)
QUERIES = [
    ("charter", "Harmonix", 1200),
    ("genre", "Indie", 600), ("genre", "Alternative", 500), ("genre", "Pop", 400),
    ("genre", "Folk", 150), ("genre", "Ambient", 120), ("genre", "Dream Pop", 100), ("genre", "Shoegaze", 80),
    ("genre", "Post-Rock", 100), ("genre", "Singer/Songwriter", 80), ("genre", "Acoustic", 80),
    ("genre", "Electronic", 120), ("genre", "Soul", 60), ("genre", "Reggae", 50), ("genre", "Country", 60),
    ("genre", "Classic Rock", 200), ("genre", "Pop Punk", 120), ("genre", "Punk", 100), ("genre", "Grunge", 80),
    ("genre", "Rock", 300), ("genre", "Pop Rock", 150), ("genre", "Blues", 50), ("genre", "Jazz", 40),
]

# Segunda tanda: (instrumento, campo, valor, máximo). Primero lo oficial (Harmonix, Neversoft y otros
# estudios, sin cupo), luego charts que también traen teclado (canciones con piano) y más géneros.
QUERIES_EXTRA = [
    ("guitar", "charter", "Harmonix", 5000), ("guitar", "charter", "Neversoft", 5000),
    ("guitar", "charter", "Vicarious Visions", 500), ("guitar", "charter", "FreeStyleGames", 500),
    ("guitar", "charter", "Beenox", 500),
    ("keys", "genre", "", 2500),
    ("guitar", "genre", "Rock", 1200), ("guitar", "genre", "Alternative", 1000), ("guitar", "genre", "Indie", 800),
    ("guitar", "genre", "Pop", 800), ("guitar", "genre", "Alternative Rock", 600), ("guitar", "genre", "Pop-Rock", 500),
    ("guitar", "genre", "Hard Rock", 500), ("guitar", "genre", "Classic Rock", 400), ("guitar", "genre", "Pop Punk", 300),
    ("guitar", "genre", "Punk", 300), ("guitar", "genre", "Indie Rock", 400), ("guitar", "genre", "J-Rock", 400),
    ("guitar", "genre", "Emo", 250), ("guitar", "genre", "Metal", 600), ("guitar", "genre", "Funk", 200),
    ("guitar", "genre", "New Wave", 150), ("guitar", "genre", "Electronic", 200), ("guitar", "genre", "Folk", 150),
    ("guitar", "genre", "Grunge", 150), ("guitar", "genre", "Anime", 80),
]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def post(path: str, body: dict, retries: int = 5) -> dict:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(f"{API}{path}", method="POST", headers={**HEADERS, "Content-Type": "application/json"},
                                         data=json.dumps(body).encode())
            return json.load(urllib.request.urlopen(req, timeout=30))
        except (urllib.error.URLError, TimeoutError) as e:
            wait = 5 * (attempt + 1)
            print("   " + t("reintento en {s} s ({err})", s=wait, err=e))
            time.sleep(wait)
    raise RuntimeError(t("Encore no responde: {path}", path=path))


def advanced(page: int, instrument: str = "guitar", **filters) -> dict:
    text = lambda v="": {"value": v, "exact": False, "exclude": False}  # noqa: E731
    body = {"per_page": 250, "page": page, "instrument": instrument, "difficulty": "expert", "drumType": None,
            "drumsReviewed": True, "sort": None, "source": "bridge", "name": text(), "artist": text(), "album": text(),
            "genre": text(), "year": text(), "charter": text(), "minLength": None, "maxLength": None,
            "minIntensity": None, "maxIntensity": None, "minAverageNPS": None, "maxAverageNPS": None,
            "minMaxNPS": None, "maxMaxNPS": None, "modifiedAfter": None, "hash": None, "hasSoloSections": None,
            "hasForcedNotes": None, "hasOpenNotes": None, "hasTapNotes": None, "hasLyrics": None, "hasVocals": None,
            "hasRollLanes": None, "has2xKick": None, "hasIssues": None, "hasVideoBackground": None, "modchart": False}
    for k, v in filters.items():
        body[k] = text(v)
    return post("/search/advanced", body)


def library_keys() -> set[str]:
    if not LIBRARY_JSON.exists():
        return set()
    return {norm(m["artist"]) + "|" + norm(m["title"]) for m in json.loads(LIBRARY_JSON.read_text(encoding="utf-8"))}


def cmd_catalog(queries: list[tuple] = QUERIES, dest: Path = CATALOG, exclude_catalogs: tuple[Path, ...] = ()) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    exclude = library_keys()
    for cat in exclude_catalogs:
        exclude |= {norm(c.get("artist")) + "|" + norm(c.get("name")) for c in json.loads(cat.read_text(encoding="utf-8"))}
    chosen: dict[str, dict] = {}
    for q in queries:
        instrument, field, value, quota = q if len(q) == 4 else ("guitar", *q)
        got, page = 0, 1
        while got < quota:
            r = advanced(page, instrument, **({field: value} if value else {}))
            data = r.get("data", [])
            if not data:
                break
            random.Random(page).shuffle(data)
            for c in data:
                key = norm(c.get("artist")) + "|" + norm(c.get("name"))
                if key in chosen or key in exclude or c.get("diff_guitar", -1) < 0:
                    continue
                if not 60000 <= (c.get("song_length") or 0) <= 480000:  # 1 a 8 minutos
                    continue
                chosen[key] = {k: c.get(k) for k in ("md5", "name", "artist", "album", "genre", "charter", "song_length",
                                                      "diff_guitar", "hasVideoBackground", "chartId")}
                chosen[key]["query"] = f"{instrument}:{field}={value}"
                got += 1
                if got >= quota:
                    break
            print(f"{instrument}:{field}={value}: " + t("página {page}, {got}/{quota} (total {total})", page=page,
                                                         got=got, quota=quota, total=len(chosen)))
            page += 1
            time.sleep(1.0)
    dest.write_text(json.dumps(list(chosen.values()), ensure_ascii=False, indent=0), encoding="utf-8")
    print("\n" + t("Catálogo: {n} charts -> {dest}", n=len(chosen), dest=dest))


def download(md5: str, dest: Path, novideo: bool) -> int:
    url = f"{FILES}/{md5}{'_novideo' if novideo else ''}.sng"
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as resp, open(tmp, "wb") as f:
        size = 0
        while chunk := resp.read(1 << 20):
            f.write(chunk)
            size += len(chunk)
    tmp.replace(dest)
    return size


def cmd_download(items: list[dict] | None = None, dest_dir: Path = SNG_DIR) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    items = items if items is not None else json.loads(CATALOG.read_text(encoding="utf-8"))
    total = sum(p.stat().st_size for p in dest_dir.glob("*.sng"))
    done = failed = 0
    t0 = time.time()
    for i, c in enumerate(items):
        dest = dest_dir / f"{c['md5']}.sng"
        if dest.exists():
            continue
        if total > BUDGET_BYTES:
            print(t("Tope de {gb:.0f} GB alcanzado.", gb=BUDGET_BYTES / 1024**3))
            break
        try:
            total += download(c["md5"], dest, bool(c.get("hasVideoBackground")))
            done += 1
        except Exception as e:  # noqa: BLE001 - un paquete roto no para la descarga
            failed += 1
            print("   " + t("fallo {name}: {err}", name=f"{c.get('artist')} - {c.get('name', c.get('title'))}", err=e))
            time.sleep(3)
            continue
        if done % 25 == 0:
            rate = total / 1024**2 / max(1, time.time() - t0)
            print(f"{i + 1}/{len(items)}: " + t("{done} bajadas, {failed} fallos, {gb:.1f} GB ({rate:.1f} MB/s)",
                                                 done=done, failed=failed, gb=total / 1024**3, rate=rate), flush=True)
        time.sleep(0.3)
    print(t("Fin: {done} bajadas, {failed} fallos, {gb:.1f} GB en {dest}", done=done, failed=failed,
            gb=total / 1024**3, dest=dest_dir))


def cmd_library() -> None:
    """Busca cada canción de la biblioteca; guarda las coincidencias y baja sus charts a out/encore/."""
    import mutagen

    progress = OUT / "library_progress.json"  # se guarda a medida que avanza: la búsqueda es lenta
    state = json.loads(progress.read_text(encoding="utf-8")) if progress.exists() else {"seen": [], "found": []}
    seen, found = set(state["seen"]), state["found"]
    files = sorted(p for p in MUSIC_DIR.rglob("*") if p.suffix.lower() in (".mp3", ".flac", ".ogg", ".m4a"))
    for i, p in enumerate(files):
        if str(p) in seen:
            continue
        tags = mutagen.File(str(p), easy=True) or {}
        title = (tags.get("title") or [""])[0]
        artist = (tags.get("artist") or [""])[0]
        if not title:
            stem = re.sub(r"^\d+\s*-\s*", "", p.stem)
            artist, _, title = stem.partition(" - ") if " - " in stem else (p.parent.parent.name, "", stem)
        r = post("/search", {"search": f"{title} {artist}", "per_page": 20, "page": 1, "instrument": "guitar",
                             "difficulty": None, "drumType": None, "source": "bridge"})
        cands = [c for c in r.get("data", []) if norm(title)[:14] and norm(title)[:14] in norm(c.get("name"))
                 and (not artist or norm(artist)[:6] in norm(c.get("artist"))) and c.get("diff_guitar", -1) >= 0]
        if cands:
            # Preferencia: Harmonix (oficial), luego la que más se parezca en duración.
            best = sorted(cands, key=lambda c: (c.get("charter") != "Harmonix", c.get("song_length") or 0))[0]
            found.append({"file": str(p), "artist": artist, "title": title, "md5": best["md5"],
                          "charter": best.get("charter"), "hasVideoBackground": best.get("hasVideoBackground"),
                          "encore_name": f"{best.get('artist')} - {best.get('name')}"})
        seen.add(str(p))
        if (i + 1) % 10 == 0:
            OUT.mkdir(parents=True, exist_ok=True)
            progress.write_text(json.dumps({"seen": sorted(seen), "found": found}, ensure_ascii=False), encoding="utf-8")
        if (i + 1) % 25 == 0:
            print(f"{i + 1}/{len(files)}: " + t("{n} con chart", n=len(found)), flush=True)
        time.sleep(1.0)
    LIBRARY_JSON.write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n" + t("{found}/{total} canciones de la biblioteca con chart humana -> {dest}", found=len(found),
                   total=len(files), dest=LIBRARY_JSON))
    cmd_download(found, ROOT / "out" / "encore")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    commands = {
        "catalog": cmd_catalog,
        "download": cmd_download,
        "catalog-extra": lambda: cmd_catalog(QUERIES_EXTRA, CATALOG_EXTRA, (CATALOG,)),
        "download-extra": lambda: cmd_download(json.loads(CATALOG_EXTRA.read_text(encoding="utf-8"))),
        "library": cmd_library,
        "library-download": lambda: cmd_download(json.loads(LIBRARY_JSON.read_text(encoding="utf-8")), ROOT / "out" / "encore"),
    }
    commands[sys.argv[1]]()
