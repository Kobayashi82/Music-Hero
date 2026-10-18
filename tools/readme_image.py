"""Imagen del README: el juego (una captura con transparencia) sobre un escritorio dibujado (fondo, un reproductor
genérico y la barra de tareas), sin nada del escritorio de verdad.

Uso:
    1. Captura del juego (sin sonido, letra ni récords: una config aparte):
       MUSICHERO_HOME=<carpeta> APPDATA=<carpeta>/appdata uv run --project app play "out/charts/<canción>"
           --autoplay --screenshot juego.png --screenshot-at 43
       con <carpeta>/appdata/MusicHero/config.json = {"language": "en", "volume": 0, "lyrics": false}
    2. uv run --project app python tools/readme_image.py juego.png docs/images/gameplay.png "Queen" "Hammer to Fall"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "src"))
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath,  # noqa: E402
                           QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QApplication  # noqa: E402

W, H, BAR = 1920, 1080, 48


def wallpaper(p: QPainter) -> None:
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QColor("#0c1230"))
    g.setColorAt(0.55, QColor("#24123f"))
    g.setColorAt(1, QColor("#0b1a2e"))
    p.fillRect(0, 0, W, H, g)
    for x, y, r, c in ((260, 860, 760, "#ff5e8a"), (1650, 180, 820, "#3d7dff"), (1500, 980, 600, "#ff9a3c"),
                       (420, 120, 520, "#7a4dff"), (980, 560, 900, "#1fc8b0")):
        rg = QRadialGradient(x, y, r)
        col = QColor(c)
        col.setAlpha(110)
        rg.setColorAt(0, col)
        col.setAlpha(0)
        rg.setColorAt(1, col)
        p.fillRect(0, 0, W, H, rg)


def rounded(p: QPainter, rect: QRectF, radius: float, color: str) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.fillPath(path, QColor(color))


def player(p: QPainter, artist: str, title: str) -> None:
    """Un reproductor de música cualquiera (sin marca), con la canción que suena."""
    x, y, w, h = 90, 330, 470, 250
    rounded(p, QRectF(x, y, w, h), 14, "#e61b1e2b")
    for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        p.setBrush(QColor(c))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(x + 22 + i * 18, y + 20), 5, 5)
    art = QLinearGradient(x + 24, y + 48, x + 144, y + 168)
    art.setColorAt(0, QColor("#ff7a59"))
    art.setColorAt(1, QColor("#7a4dff"))
    path = QPainterPath()
    path.addRoundedRect(QRectF(x + 24, y + 48, 120, 120), 10, 10)
    p.fillPath(path, art)
    p.setPen(QColor("white"))
    p.setFont(QFont("Segoe UI", 20, QFont.Weight.DemiBold))
    p.drawText(QRectF(x + 164, y + 62, w - 180, 34), Qt.AlignmentFlag.AlignLeft, title)
    p.setPen(QColor("#b0b4c8"))
    p.setFont(QFont("Segoe UI", 14))
    p.drawText(QRectF(x + 164, y + 100, w - 180, 26), Qt.AlignmentFlag.AlignLeft, artist)
    bar = QRectF(x + 24, y + 196, w - 48, 6)
    rounded(p, bar, 3, "#3a3e52")
    rounded(p, QRectF(bar.x(), bar.y(), bar.width() * 0.19, 6), 3, "#ffffff")
    p.setFont(QFont("Segoe UI", 11))
    p.drawText(QRectF(bar.x(), y + 208, 80, 20), Qt.AlignmentFlag.AlignLeft, "0:41")
    p.drawText(QRectF(bar.right() - 80, y + 208, 80, 20), Qt.AlignmentFlag.AlignRight, "3:40")
    cx = x + w / 2
    p.setBrush(QColor("white"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(QRectF(cx - 9, y + 214, 6, 20))  # pausa
    p.drawRect(QRectF(cx + 3, y + 214, 6, 20))
    for d in (-1, 1):  # anterior / siguiente
        tip = cx + d * 64
        p.drawPolygon(QPolygonF([QPointF(tip, y + 224), QPointF(tip - d * 14, y + 215), QPointF(tip - d * 14, y + 233)]))


def taskbar(p: QPainter) -> None:
    from app.play import icon_pixmap

    p.fillRect(0, H - BAR, W, BAR, QColor(18, 20, 30, 225))
    p.fillRect(0, H - BAR, W, 1, QColor(255, 255, 255, 30))
    colors = ("#4f8cff", "#f4b400", "#34a853", "#a259ff", "#ff6d5a", "#21c7c7")
    x0 = W / 2 - len(colors) * 22
    for i, c in enumerate(colors):  # aplicaciones cualesquiera
        rounded(p, QRectF(x0 + i * 44 + 8, H - BAR + 10, 28, 28), 7, c)
    p.drawPixmap(W - 172, H - BAR + 12, icon_pixmap(24))  # Music Hero junto al reloj
    p.setPen(QColor("white"))
    p.setFont(QFont("Segoe UI", 11))
    p.drawText(QRectF(W - 136, H - BAR, 120, BAR), Qt.AlignmentFlag.AlignCenter, "21:47")


def main() -> int:
    if len(sys.argv) < 5:
        print(__doc__)
        return 1
    shot, out, artist, title = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    app = QApplication.instance() or QApplication([])  # noqa: F841 - QPixmap y las fuentes necesitan la aplicación
    game = QImage(str(shot))
    game = game.scaledToHeight(H - BAR, Qt.TransformationMode.SmoothTransformation)
    img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    wallpaper(p)
    player(p, artist, title)
    p.drawImage(int((W - game.width()) / 2), 0, game)  # como en el juego: centrado, de arriba a la barra de tareas
    taskbar(p)
    p.end()
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convertToFormat(QImage.Format.Format_RGB32).save(str(out))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
