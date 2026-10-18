"""Los sprites del overlay se dibujan todos y no salen vacíos. uv run --project app --with pytest pytest app/tests"""

from PySide6.QtGui import QGuiApplication

from app import sprites

app = QGuiApplication.instance() or QGuiApplication([])


def test_todos_los_sprites_se_dibujan():
    ids = [f"gem/{lane}/{k}" for lane in range(5) for k in ("normal", "hopo", "miss", "star", "starhopo")]
    ids += [f"fret/{lane}/{k}" for lane in range(5) for k in ("up", "down")]
    ids += [f"flame/{lane}/{f}" for lane in range(5) for f in range(sprites.FLAME_FRAMES)]
    ids += [f"glow/{g}" for g in ("0", "4", "white")]
    ids += [f"tail/{lane}/{k}" for lane in range(5) for k in ("normal", "live", "miss", "star", "starlive")]
    ids += [f"side/{s}/{k}" for s in (0, 1) for k in ("glow", "spark")]
    for sid in ids:
        img = sprites.draw(sid)
        center = img.pixelColor(img.width() // 2, int(img.height() * 0.45))
        assert not img.isNull() and img.width() > 0, sid
        if not sid.startswith("flame"):
            assert center.alpha() > 0, sid
