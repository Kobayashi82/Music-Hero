"""Sprites del overlay: entre Rock Band y neón. Materiales creíbles (bisel metálico, tapa de color como cristal
con luz por dentro, brillo amplio y suave, sin sombras) y algo de luz emitida. Se dibujan con QPainter
una vez, al doble de resolución (más nítidos al reducir), y QML solo los escala (image://sprites/<id>).

Ids:
    gem/<carril>/<normal|hopo|miss>    nota (GEM_W x GEM_H, con sitio para el halo; la cara es FACE)
    fret/<carril>/<up|down>            botón de la línea de golpeo (mismo lienzo y cara que las notas)
    flame/<carril>/<0..FLAME_FRAMES-1> acierto: fuego suave, haz de luz y chispas (base abajo en el centro)
    glow/<carril|white>                halo suave redondo (GLOW x GLOW)
"""

from __future__ import annotations

import random

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtQuick import QQuickImageProvider

COLORS = ["#2ecc40", "#ff4136", "#ffdc00", "#1e90ff", "#ff851b"]
GEM_W, GEM_H = 256, 160
FACE = QRectF(38, 34, 180, 82)  # elipse de la cara dentro del lienzo (Highway.qml: gemScale, faceY)
DEPTH = 16  # grosor de la pieza
FLAME_W, FLAME_H, FLAME_BASE, FLAME_FRAMES = 160, 320, 34, 6
GLOW = 256
SS = 2  # superresolución


# ---------- utilidades ----------

def _img(w: float, h: float) -> tuple[QImage, QPainter]:
    """Lienzo de w x h (en unidades del sprite) a SS veces la resolución, con el pintor ya escalado."""
    img = QImage(int(w * SS), int(h * SS), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(SS, SS)
    return img, p


def _paste(p: QPainter, img: QImage, opacity: float = 1.0) -> None:
    p.save()
    p.resetTransform()
    p.setOpacity(opacity)
    p.drawImage(0, 0, img)
    p.restore()


def _finish(img: QImage) -> QImage:
    return img.scaled(img.width() // SS, img.height() // SS, Qt.AspectRatioMode.IgnoreAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)


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
    w, h = img.width(), img.height()
    smooth, ignore = Qt.TransformationMode.SmoothTransformation, Qt.AspectRatioMode.IgnoreAspectRatio
    small = img.scaled(max(1, w // factor), max(1, h // factor), ignore, smooth)
    mid = small.scaled(max(1, w // 2), max(1, h // 2), ignore, smooth)
    return mid.scaled(w, h, ignore, smooth)


def _soft(w: float, h: float, paint, factor: int) -> QImage:
    """Lo que pinta paint(p), desenfocado (para halos, sombras y brillos suaves)."""
    layer, p = _img(w, h)
    paint(p)
    p.end()
    return _blur(layer, factor * SS)


_grain_cache: dict[tuple[int, int], QImage] = {}


def _grain(w: int, h: int) -> QImage:
    """Ruido fino (claro y oscuro) para quitar el aspecto de degradado de ordenador."""
    key = (w, h)
    if key not in _grain_cache:
        rng = np.random.default_rng(7)
        v = rng.integers(0, 256, (h, w), dtype=np.uint8)
        a = rng.integers(0, 12, (h, w), dtype=np.uint8)
        arr = np.dstack([v, v, v, a]).copy()
        img = QImage(arr.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        _grain_cache[key] = img
    return _grain_cache[key]


def _ellipse(r: QRectF) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(r)
    return path


def _body(face: QRectF, depth: float) -> QPainterPath:
    """Silueta de una pieza redonda con grosor, vista en perspectiva desde arriba."""
    band = QPainterPath()
    band.addRect(QRectF(face.left(), face.center().y(), face.width(), depth))
    return _ellipse(face).united(_ellipse(face.translated(0, depth))).united(band)


def _side(p: QPainter, face: QRectF, depth: float, light: QColor, dark: QColor) -> None:
    """Canto cilíndrico: oscuro en los bordes, más claro un poco a la izquierda (luz de arriba-izquierda)."""
    g = QLinearGradient(face.left(), 0, face.right(), 0)
    g.setColorAt(0, _shade(dark, 0.6))
    g.setColorAt(0.3, light)
    g.setColorAt(0.55, dark)
    g.setColorAt(0.85, _shade(light, 0.8))
    g.setColorAt(1, _shade(dark, 0.5))
    p.setPen(QPen(QColor(0, 0, 0, 200), 1.5))
    p.setBrush(QBrush(g))
    p.drawPath(_body(face, depth))


def _halo(p: QPainter, shape: QPainterPath, col: QColor, strength: float) -> None:
    def paint(q: QPainter) -> None:
        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(col)
        q.drawPath(shape)
    _paste(p, _soft(GEM_W, GEM_H, paint, 9), strength)


def _bezel(p: QPainter, r: QRectF, tint: QColor | None = None) -> None:
    """Aro metálico (cromo) o del color dado, iluminado desde arriba."""
    g = QLinearGradient(0, r.top(), 0, r.bottom())
    if tint is None:
        g.setColorAt(0, QColor("#f4f5f8"))
        g.setColorAt(0.25, QColor("#b9bdc7"))
        g.setColorAt(0.55, QColor("#5d616b"))
        g.setColorAt(0.8, QColor("#9196a1"))
        g.setColorAt(1, QColor("#3a3d45"))
    else:
        g.setColorAt(0, _shade(tint, 1.55))
        g.setColorAt(0.3, tint)
        g.setColorAt(0.6, _shade(tint, 0.55))
        g.setColorAt(1, _shade(tint, 0.8))
    p.setPen(QPen(QColor(0, 0, 0, 180), 1.5))
    p.setBrush(QBrush(g))
    p.drawEllipse(r)


def _glass(p: QPainter, r: QRectF, col: QColor, lit: float, frosted: bool = False) -> None:
    """Tapa de color como cristal: luz que sale de dentro (más abajo del centro), borde de Fresnel y brillo
    amplio y suave arriba. lit: 0 apagado .. 1 encendido."""
    g = QRadialGradient(QPointF(r.center().x(), r.center().y() + r.height() * 0.12), r.width() * 0.56)
    if frosted:  # HOPO: cristal blanco esmerilado, encendido
        g.setColorAt(0, QColor("white"))
        g.setColorAt(0.6, _shade(col, 1.78))
        g.setColorAt(1, _shade(col, 1.4))
    else:
        g.setColorAt(0, _shade(col, 1.0 + 0.55 * lit))
        g.setColorAt(0.55, _shade(col, 0.75 + 0.25 * lit))
        g.setColorAt(1, _shade(col, 0.42 + 0.2 * lit))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawEllipse(r)
    p.save()  # grano dentro de la tapa
    p.setClipPath(_ellipse(r))
    _paste(p, _grain(int(GEM_W * SS), int(GEM_H * SS)))
    p.restore()
    rim = QRadialGradient(r.center(), r.width() * 0.5)  # Fresnel: el borde de la tapa recoge luz
    rim.setColorAt(0.78, _alpha(_shade(col, 1.6), 0))
    rim.setColorAt(0.97, _alpha(_shade(col, 1.7), 0.55))
    rim.setColorAt(1, _alpha(_shade(col, 1.8), 0))
    p.save()
    p.scale(1, r.height() / r.width())  # el degradado radial es circular: se aplasta con la elipse
    c = r.center()
    p.translate(0, c.y() * (r.width() / r.height() - 1))
    rim.setCenter(c)
    rim.setFocalPoint(c)
    p.setBrush(QBrush(rim))
    p.drawEllipse(QRectF(r.left(), c.y() - r.width() / 2, r.width(), r.width()))
    p.restore()

    def spec(q: QPainter) -> None:  # brillo del foco: ancho, arriba, suave
        hl = QRectF(r.left() + r.width() * 0.14, r.top() + r.height() * 0.06, r.width() * 0.62, r.height() * 0.3)
        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(QColor(255, 255, 255, 150))
        q.drawEllipse(hl)
    p.save()
    p.setClipPath(_ellipse(r))
    _paste(p, _soft(GEM_W, GEM_H, spec, 3), 0.6 if not frosted else 0.4)
    p.restore()
    p.setPen(QPen(_alpha(QColor("black"), 0.45), 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(r)


# ---------- piezas ----------

def draw_gem(lane: int, kind: str) -> QImage:
    miss = kind == "miss"
    col = QColor("#5a5e68") if miss else QColor(COLORS[lane])
    img, p = _img(GEM_W, GEM_H)
    if not miss:
        _halo(p, _body(FACE, DEPTH), _shade(col, 1.3) if kind == "hopo" else col, 0.55 if kind == "hopo" else 0.35)
    if kind == "hopo":
        _side(p, FACE, DEPTH, _shade(col, 0.8), _shade(col, 0.35))
        _bezel(p, FACE, col)  # aro del color y tapa blanca: se toca sin strum
    else:
        _side(p, FACE, DEPTH, QColor("#5d616c"), QColor("#16171c"))
        _bezel(p, FACE, QColor("#7a7e88") if miss else None)
    cap = FACE.adjusted(13, 7, -13, -9)
    lift = 5  # la tapa sobresale un poco del aro
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_shade(col, 0.35))
    p.drawPath(_body(cap.translated(0, -lift), lift))
    _glass(p, cap.translated(0, -lift), col, 0.0 if miss else 0.75, frosted=kind == "hopo")
    p.end()
    return _finish(img)


def draw_fret(lane: int, down: bool) -> QImage:
    col = QColor(COLORS[lane])
    img, p = _img(GEM_W, GEM_H)
    press = 6 if down else 0
    face = FACE.translated(0, press)
    lens = face.adjusted(16, 9, -16, -9)
    if down:
        _halo(p, _ellipse(lens.adjusted(-10, -6, 10, 6)), col, 1.4)
    _side(p, face, DEPTH - press, QColor("#4a4d57"), QColor("#121318"))
    _bezel(p, face)
    p.setPen(QPen(QColor(0, 0, 0, 200), 2))  # hueco del cristal
    p.setBrush(QColor("#08080c"))
    p.drawEllipse(lens.adjusted(-3, -2, 3, 2))
    if down:
        _glass(p, lens, col, 1.0)

        def core(q: QPainter) -> None:
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(QColor(255, 255, 255, 230))
            q.drawEllipse(QRectF(0, 0, lens.width() * 0.45, lens.height() * 0.45).translated(
                lens.center() - QPointF(lens.width() * 0.225, lens.height() * 0.225)))
        _paste(p, _soft(GEM_W, GEM_H, core, 4), 0.9)
    else:  # cristal ahumado del color, con el reflejo del foco
        dark = _shade(col, 0.32)
        _glass(p, lens, dark, 0.15)
        p.setPen(QPen(_alpha(col, 0.55), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(lens.adjusted(2, 1.5, -2, -1.5))
    p.end()
    return _finish(img)


def _tongue(cx: float, base: float, w: float, h: float, sway: float) -> QPainterPath:
    path = QPainterPath(QPointF(cx - w / 2, base))
    path.cubicTo(QPointF(cx - w * 0.62, base - h * 0.42), QPointF(cx + sway - w * 0.12, base - h * 0.72),
                 QPointF(cx + sway, base - h))
    path.cubicTo(QPointF(cx + sway + w * 0.12, base - h * 0.72), QPointF(cx + w * 0.62, base - h * 0.42),
                 QPointF(cx + w / 2, base))
    path.quadTo(QPointF(cx, base + w * 0.42), QPointF(cx - w / 2, base))
    return path


def draw_flame(lane: int, frame: int) -> QImage:
    """Acierto: fuego suave del color del carril (blanco en la base), un haz de luz y chispas con estela."""
    col = QColor(COLORS[lane])
    rnd = random.Random(lane * 100 + frame)
    cx, base = FLAME_W / 2, FLAME_H - FLAME_BASE
    tongues = []
    for wf, hf, c0, c1, a in [(1.0, 0.62, _shade(col, 1.2), col, 0.6), (0.62, 0.78, _shade(col, 1.5), _shade(col, 1.1), 0.8),
                              (0.26, 0.42, QColor("white"), _shade(col, 1.65), 0.8)]:
        n = 3 if wf > 0.5 else 1
        for k in range(n):
            off = (k - (n - 1) / 2) * FLAME_W * 0.16 * wf + rnd.uniform(-3, 3)
            h = (FLAME_H - FLAME_BASE - 30) * hf * rnd.uniform(0.75, 1.0) * (1 if k == n // 2 else 0.75)
            w = FLAME_W * 0.4 * wf * rnd.uniform(0.85, 1.1)
            tongues.append((cx + off, w, h, rnd.uniform(-1, 1) * FLAME_W * 0.08, c0, c1, a))

    def fire(q: QPainter) -> None:
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        q.setPen(Qt.PenStyle.NoPen)
        for x, w, h, sway, c0, c1, a in tongues:
            g = QLinearGradient(0, base + 8, 0, base - h)
            g.setColorAt(0, _alpha(c0, a))
            g.setColorAt(0.35, _alpha(c1, a * 0.85))
            g.setColorAt(0.75, _alpha(col, a * 0.35))
            g.setColorAt(1, _alpha(col, 0))
            q.setBrush(QBrush(g))
            q.drawPath(_tongue(x, base, w, h, sway))

    def beam(q: QPainter) -> None:
        h = (FLAME_H - FLAME_BASE - 20) * rnd.uniform(0.85, 1.0)
        g = QLinearGradient(0, base, 0, base - h)
        g.setColorAt(0, QColor(255, 255, 255, 230))
        g.setColorAt(0.25, _alpha(_shade(col, 1.5), 0.7))
        g.setColorAt(1, _alpha(col, 0))
        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(QBrush(g))
        q.drawPath(_tongue(cx, base, 14, h, 0))

    img, p = _img(FLAME_W, FLAME_H)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    halo = _soft(FLAME_W, FLAME_H, fire, 5)
    _paste(p, halo)
    _paste(p, halo, 0.6)
    fire(p)
    _paste(p, _soft(FLAME_W, FLAME_H, beam, 3))
    for _ in range(8):  # chispas con estela
        x = cx + rnd.uniform(-0.36, 0.36) * FLAME_W
        y = base - rnd.uniform(0.25, 0.9) * (FLAME_H - FLAME_BASE - 30)
        trail = rnd.uniform(10, 24)
        dx = (x - cx) * 0.12
        g = QLinearGradient(x, y, x - dx, y + trail)
        g.setColorAt(0, QColor(255, 255, 240, 240))
        g.setColorAt(1, _alpha(col, 0))
        p.setPen(QPen(QBrush(g), rnd.uniform(1.6, 2.8), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(x, y), QPointF(x - dx, y + trail))
    p.end()
    return _finish(img)


def draw_glow(name: str) -> QImage:
    col = QColor("white") if name == "white" else QColor(COLORS[int(name)])
    img = QImage(GLOW, GLOW, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
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
