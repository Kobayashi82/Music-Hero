"""Construye la app instalable (fase 7): PyInstaller en modo carpeta y, si está Inno Setup, el instalador.

    uv run --project app --with pyinstaller python packaging/build.py [--no-installer]

Deja en build/stage lo que va dentro además del código de la app: el código del motor (generator: pyproject,
uv.lock y src, sin cachés), OnsetNet (models/best.pt, con el mismo nombre: así las charts hechas en desarrollo
valen tal cual en la instalada), uv.exe y el icono. La app queda en
build/dist/Music Hero/ y el instalador en build/installer/.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "build"
STAGE = BUILD / "stage"
ISCC_PLACES = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
               Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
               Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe"]


def stage() -> None:
    shutil.rmtree(STAGE, ignore_errors=True)
    engine = STAGE / "engine_src"
    engine.mkdir(parents=True)
    for f in ("pyproject.toml", "uv.lock"):
        shutil.copy2(REPO / "generator" / f, engine / f)
    shutil.copytree(REPO / "generator" / "src", engine / "src",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
    shutil.copy2(REPO / "models" / "best.pt", STAGE / "best.pt")
    uv = shutil.which("uv")
    if uv is None:
        sys.exit("falta uv.exe (va dentro de la app para instalar el motor)")
    shutil.copy2(uv, STAGE / "uv.exe")

    sys.path.insert(0, str(REPO / "app" / "src"))
    from PySide6.QtWidgets import QApplication

    from app.play import icon_pixmap

    app = QApplication.instance() or QApplication([])  # noqa: F841 - QPixmap necesita la aplicación
    write_ico(STAGE / "music_hero.ico", [png_bytes(icon_pixmap(s)) for s in ICO_SIZES])


ICO_SIZES = (16, 24, 32, 48, 64, 256)


def png_bytes(pix) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not pix.save(buf, "PNG"):
        sys.exit("no se pudo guardar el icono")
    return bytes(data)


def write_ico(path: Path, pngs: list[bytes]) -> None:
    """.ico con varios tamaños (Qt solo escribe uno): cabecera, una entrada por tamaño y cada imagen en PNG."""
    import struct

    out = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    for size, png in zip(ICO_SIZES, pngs):
        out += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    path.write_bytes(out + b"".join(pngs))


def size_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 2**20


def find_iscc() -> Path | None:
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    return next((p for p in ISCC_PLACES if p.is_file()), None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-installer", action="store_true", help="solo la carpeta de PyInstaller")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    stage()
    print("build/stage listo")
    import PyInstaller.__main__

    PyInstaller.__main__.run([str(REPO / "packaging" / "music_hero.spec"), "--noconfirm", "--clean",
                              "--distpath", str(BUILD / "dist"), "--workpath", str(BUILD / "work")])
    dist = BUILD / "dist" / "Music Hero"
    print(f"app: {dist} ({size_mb(dist):.0f} MB)")
    if args.no_installer:
        return 0
    iscc = find_iscc()
    if iscc is None:
        print("Inno Setup no está instalado: falta el instalador (winget install JRSoftware.InnoSetup)")
        return 0
    version = "0.1.0"
    subprocess.run([str(iscc), f"/DAppVersion={version}", str(REPO / "packaging" / "music_hero.iss")], check=True)
    out = BUILD / "installer" / f"MusicHero-Setup-{version}.exe"
    print(f"instalador: {out} ({out.stat().st_size / 2**20:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
