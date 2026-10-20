# PyInstaller, modo carpeta (no onefile: arranque lento y falsos positivos de antivirus). Lo lanza packaging/build.py,
# que deja antes en build/stage lo que va dentro además del código: el del motor, OnsetNet, uv.exe y el icono.
from pathlib import Path

REPO = Path(SPECPATH).parent  # noqa: F821 - lo define PyInstaller
STAGE = REPO / "build" / "stage"

a = Analysis(  # noqa: F821
    [str(REPO / "packaging" / "music_hero.py")],
    pathex=[str(REPO / "app" / "src")],
    datas=[
        (str(REPO / "app" / "src" / "app" / "qml"), "app/qml"),
        (str(STAGE / "engine_src"), "engine_src"),
        (str(STAGE / "best.pt"), "models"),
        (str(STAGE / "uv.exe"), "."),
    ],
    excludes=["tkinter", "unittest", "pydoc", "torch", "winrt", "IPython", "matplotlib"],
    noarchive=False,
)
# lo que no se usa: OpenGL por software (el juego va con Direct3D 11), traducciones de Qt, PDF, teclado virtual
UNUSED = ("opengl32sw.dll", "translations", "Qt6Pdf", "Qt6VirtualKeyboard")
a.binaries = [b for b in a.binaries if not any(x in b[0] for x in UNUSED)]
a.datas = [d for d in a.datas if not any(x in d[0] for x in UNUSED)]
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Music Hero",
    console=False,
    icon=str(STAGE / "music_hero.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Music Hero")  # noqa: F821
