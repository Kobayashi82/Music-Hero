"""Sprites del overlay, estilo neón: formas limpias, borde fino brillante y luz emitida (glow), sin brillos
de plástico. Se dibujan con QPainter una vez, en alta resolución, y QML solo los escala (image://sprites/<id>).

Ids:
    gem/<carril>/<normal|hopo|miss>    nota (GEM_W x GEM_H, con sitio para el halo; la cara es FACE)
    fret/<carril>/<up|down>            botón de la línea de golpeo (mismo lienzo y cara que las notas)
    flame/<carril>/<0..FLAME_FRAMES-1> destello de acierto: haz de luz y chispas (base abajo en el centro)
    glow/<carril|white>                halo suave redondo (GLOW x GLOW)
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtQuick import QQuickImageProvider

COLORS = ["#2ecc40", "#ff4136", "#ffdc00", "#1e90ff", "#ff851b"]
GEM_W, GEM_H = 256, 160
FACE = QRectF(38, 34, 180, 82)  # elipse de la cara dentro del lienzo (el resto es halo)
DEPTH = 12  # grosor de la nota, plano
FLAME_W, FLAME_H, FLAME_BASE, FLAME_FRAMES = 160, 320, 34, 6
GLOW = 256


def _img(w: int, h: int) -> tuple[QImage, QPainter]:
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    return img, p


def _shade(c: QColor, f: float) -> QColor:
    """f > 1 aclara hacia blanco (2 = blanco), f < 1 oscurece."""
    if f >= 1:
        t = min(1.0, f - 1)
        return QColor.fromRgbF(c.redF() + (1 - c.redF()) * t, c.greenF() + (1 - c.greenF()) * t,
                               c.blueF() + (1 - c.blueF()) * t, c.alphaF())
    return QColor.fromRgbF(c.redF() * f, c.greenF() * f, c.blueF() * f, c.alphaF())


def _alpha(c: QColor, a: float) -> QColor:
    c = QColor(c)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


def _blur(img: QImage, factor: int) -> QImage:
    """Desenfoque barato y suave: reducir y volver a ampliar en dos pasos."""
    w, h = img.width(), img.height()
    smooth, ignore = Qt.TransformationMode.SmoothTransformation, Qt.AspectRatioMode.IgnoreAspectRatio
    small = img.scaled(max(1, w // factor), max(1, h // factor), ignore, smooth)
    mid = small.scaled(max(1, w // 2), max(1, h // 2), ignore, smooth)
    return mid.scaled(w, h, ignore, smooth)


def _glow_of(w: int, h: int, paint, factor: int, strength: float = 1.0) -> QImage:
    """Halo: lo que pinta paint(p), desenfocado; strength > 1 lo repite para que brille más."""
    layer, p = _img(w, h)
    paint(p)
    p.end()
    blurred = _blur(layer, factor)
    out, p = _img(w, h)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    while strength > 0:
        p.setOpacity(min(1.0, strength))
        p.drawImage(0, 0, blurred)
        strength -= 1
    p.end()
    return out


def _body_path(face: QRectF, depth: float) -> QPainterPath:
    top = QPainterPath()
    top.addEllipse(face)
    low = QPainterPath()
    low.addEllipse(face.translated(0, depth))
    band = QPainterPath()
    band.addRect(QRectF(face.left(), face.center().y(), face.width(), depth))
    return top.united(low).united(band)


def draw_gem(lane: int, kind: str) -> QImage:
    miss = kind == "miss"
    col = QColor("#4a4e5a") if miss else QColor(COLORS[lane])
    body = _body_path(FACE, DEPTH)
    img, p = _img(GEM_W, GEM_H)
    if not miss:  # halo del color de la nota (los HOPO, más blanco y fuerte)
        def halo(q: QPainter) -> None:
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(_shade(col, 1.35) if kind == "hopo" else col)
            q.drawPath(body)
        p.drawImage(0, 0, _glow_of(GEM_W, GEM_H, halo, 10, 1.3 if kind == "hopo" else 0.85))
    p.setPen(QPen(QColor(0, 0, 0, 170), 2))  # canto: plano y oscuro
    p.setBrush(_shade(col, 0.42))
    p.drawPath(body)
    if kind == "hopo":  # aro de color y cara blanca encendida: se toca sin strum
        g = QLinearGradient(0, FACE.top(), 0, FACE.bottom())
        g.setColorAt(0, _shade(col, 1.2))
        g.setColorAt(1, _shade(col, 0.85))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(FACE)
        inner = FACE.adjusted(17, 9, -17, -9)
        g = QRadialGradient(inner.center(), inner.width() * 0.55)
        g.setColorAt(0, QColor("white"))
        g.setColorAt(0.7, _shade(col, 1.8))
        g.setColorAt(1, _shade(col, 1.55))
        p.setBrush(QBrush(g))
        p.drawEllipse(inner)
        p.setPen(QPen(_shade(col, 1.9), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(FACE.adjusted(2, 1.5, -2, -1.5))
    else:
        g = QLinearGradient(0, FACE.top(), 0, FACE.bottom())
        g.setColorAt(0, _shade(col, 1.12))
        g.setColorAt(0.55, col)
        g.setColorAt(1, _shade(col, 0.8))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(FACE)
        p.setPen(QPen(_alpha(_shade(col, 1.65), 0.5 if miss else 0.95), 3))  # filo de neón
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(FACE.adjusted(5, 3, -5, -3))
        core = QRectF(0, 0, FACE.width() * 0.26, FACE.height() * 0.3)
        core.moveCenter(FACE.center())
        if not miss:
            def light(q: QPainter) -> None:
                q.setPen(Qt.PenStyle.NoPen)
                q.setBrush(QColor("white"))
                q.drawEllipse(core.adjusted(-4, -3, 4, 3))
            p.drawImage(0, 0, _glow_of(GEM_W, GEM_H, light, 5, 0.7))
        g = QRadialGradient(core.center(), core.width() * 0.6)
        g.setColorAt(0, QColor("white") if not miss else QColor("#8a8e98"))
        g.setColorAt(1, _shade(col, 1.6) if not miss else QColor("#6a6e78"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(core)
    p.end()
    return img


def draw_fret(lane: int, down: bool) -> QImage:
    col = QColor(COLORS[lane])
    img, p = _img(GEM_W, GEM_H)
    ring = FACE.adjusted(4, 2, -4, -2)

    def halo(q: QPainter) -> None:
        if down:
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(col)
            q.drawEllipse(ring)
        else:
            q.setPen(QPen(col, 8))
            q.setBrush(Qt.BrushStyle.NoBrush)
            q.drawEllipse(ring)
    p.drawImage(0, 0, _glow_of(GEM_W, GEM_H, halo, 9, 1.6 if down else 0.8))
    if down:  # encendido: lleno de luz, blanco en el centro
        g = QRadialGradient(ring.center(), ring.width() * 0.52)
        g.setColorAt(0, QColor("white"))
        g.setColorAt(0.35, _shade(col, 1.6))
        g.setColorAt(0.85, col)
        g.setColorAt(1, _shade(col, 0.8))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(ring)
        p.setPen(QPen(_shade(col, 1.85), 4))
    else:  # apagado: hueco oscuro con el aro de color y un poco de su luz dentro
        g = QRadialGradient(ring.center(), ring.width() * 0.52)
        g.setColorAt(0, _alpha(col, 0.18))
        g.setColorAt(0.7, QColor(6, 6, 12, 200))
        g.setColorAt(1, QColor(6, 6, 12, 220))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(ring)
        p.setPen(QPen(_alpha(col, 0.35), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(ring.adjusted(16, 8, -16, -8))
        p.setPen(QPen(_shade(col, 1.25), 5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(ring)
    p.setPen(QPen(_alpha(QColor("white"), 0.55 if down else 0.3), 1.5))  # filo interior del aro
    p.drawEllipse(ring.adjusted(4, 2.5, -4, -2.5))
    p.end()
    return img


def draw_flame(lane: int, frame: int) -> QImage:
    """Destello de acierto: haz de luz vertical, un filo horizontal en la base y chispas que suben."""
    col = QColor(COLORS[lane])
    rnd = random.Random(lane * 100 + frame)
    cx, base = FLAME_W / 2, FLAME_H - FLAME_BASE

    def beams(q: QPainter, core: bool) -> None:
        q.setPen(Qt.PenStyle.NoPen)
        specs = [(0.0, 1.0, 1.0)] + [(rnd.uniform(-1, 1) * 9, rnd.uniform(0.45, 0.7), 0.55) for _ in range(2)]
        for angle, hf, wf in specs:
            h = (FLAME_H - FLAME_BASE - 20) * hf * rnd.uniform(0.82, 1.0)
            w = (16 if core else 48) * wf
            q.save()
            q.translate(cx, base)
            q.rotate(angle)
            g = QLinearGradient(0, 0, 0, -h)
            g.setColorAt(0, QColor("white") if core else _shade(col, 1.5))
            g.setColorAt(0.3, _shade(col, 1.7) if core else col)
            g.setColorAt(1, _alpha(col, 0))
            q.setBrush(QBrush(g))
            path = QPainterPath(QPointF(-w / 2, 0))
            path.cubicTo(QPointF(-w / 2, -h * 0.5), QPointF(-w * 0.12, -h * 0.85), QPointF(0, -h))
            path.cubicTo(QPointF(w * 0.12, -h * 0.85), QPointF(w / 2, -h * 0.5), QPointF(w / 2, 0))
            path.quadTo(QPointF(0, w * 0.5), QPointF(-w / 2, 0))
            q.drawPath(path)
            q.restore()

    def flare(q: QPainter) -> None:
        g = QRadialGradient(QPointF(cx, base), FLAME_W * 0.5)
        g.setColorAt(0, QColor("white"))
        g.setColorAt(0.3, _shade(col, 1.4))
        g.setColorAt(1, _alpha(col, 0))
        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(QBrush(g))
        q.drawEllipse(QPointF(cx, base), FLAME_W * 0.5, 11)

    img, p = _img(FLAME_W, FLAME_H)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    state = rnd.getstate()
    p.drawImage(0, 0, _glow_of(FLAME_W, FLAME_H, lambda q: beams(q, False), 6, 2.2))
    rnd.setstate(state)  # el núcleo nítido sigue a los mismos haces
    beams(p, True)
    p.drawImage(0, 0, _glow_of(FLAME_W, FLAME_H, flare, 4, 1.2))
    flare(p)
    for _ in range(9):  # chispas con estela
        x = cx + rnd.uniform(-0.38, 0.38) * FLAME_W
        y = base - rnd.uniform(0.15, 0.85) * (FLAME_H - FLAME_BASE - 30)
        trail = rnd.uniform(10, 26)
        dx = (x - cx) * 0.12
        g = QLinearGradient(x, y, x - dx, y + trail)
        g.setColorAt(0, QColor(255, 255, 255, 240))
        g.setColorAt(1, _alpha(col, 0))
        p.setPen(QPen(QBrush(g), rnd.uniform(1.8, 3.2), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(x, y), QPointF(x - dx, y + trail))
    p.end()
    return img


def draw_glow(name: str) -> QImage:
    col = QColor("white") if name == "white" else QColor(COLORS[int(name)])
    img, p = _img(GLOW, GLOW)
    g = QRadialGradient(QPointF(GLOW / 2, GLOW / 2), GLOW / 2)
    for t in range(11):  # caída suave, sin borde
        x = t / 10
        g.setColorAt(x, _alpha(_shade(col, 1.0 + 0.5 * (1 - x) ** 3), (1 - x) ** 2 * 0.9))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawEllipse(QRectF(0, 0, GLOW, GLOW))
    p.end()
    return img


def draw(sprite_id: str) -> QImage:
    parts = sprite_id.split("/")
    kind = parts[0]
    if kind == "gem":
        return draw_gem(int(parts[1]), parts[2])
    if kind == "fret":
        return draw_fret(int(parts[1]), parts[2] == "down")
    if kind == "flame":
        return draw_flame(int(parts[1]), int(parts[2]) % FLAME_FRAMES)
    if kind == "glow":
        return draw_glow(parts[1])
    raise KeyError(sprite_id)


class SpriteProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._cache: dict[str, QImage] = {}

    def requestImage(self, sprite_id: str, size: QSize, requested: QSize) -> QImage:  # noqa: N802 - API de Qt
        img = self._cache.get(sprite_id)
        if img is None:
            img = self._cache[sprite_id] = draw(sprite_id)
        return img


def contact_sheet() -> QImage:
    """Todos los sprites en una imagen, para revisarlos."""
    ids = [f"gem/{lane}/{k}" for k in ("normal", "hopo", "miss") for lane in range(5)]
    ids += [f"fret/{lane}/{k}" for k in ("up", "down") for lane in range(5)]
    flames = [f"flame/{lane}/{f}" for lane in range(5) for f in (0, 3)]
    half = GEM_W // 2
    fh = int(FLAME_H * half / FLAME_W)
    sheet = QImage(GEM_W * 5, GEM_H * 5 + fh, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#0b0b14"))
    p = QPainter(sheet)
    for i, sid in enumerate(ids):
        p.drawImage(GEM_W * (i % 5), GEM_H * (i // 5), draw(sid))
    for i, sid in enumerate(flames):
        p.drawImage(i * half, GEM_H * 5, draw(sid).scaled(half, fh, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                            Qt.TransformationMode.SmoothTransformation))
    p.end()
    return sheet


assert math.isclose(FACE.width() / GEM_W, 180 / 256)  # Highway.qml: gemScale y faceY dependen de FACE
