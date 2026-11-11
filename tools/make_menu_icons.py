"""Draw the VRChat menu's icons into docs/unity/icons/ (512 px PNGs).

Same style as OscGoesPurrr's menu (its tools/make_menu_icons.py, Blise's
"Flat" avatar icons): white line art with round caps on a transparent
ground, a few solid shapes, and colour only where it means something -- the
518 green for what changes YOUR height, red for Stop. Numbered actions carry
a green badge with the slot number, like OGP's toy / shocker slots.

The main menu entry (menu.png) is HeightShift's app icon, as OGP's is: it
comes from _hub\\design\\icons518.py (glyph "heightshift"), which lists this
file among its targets. This script only draws the actions.

VRChat shows menu icons at 256 px at most; the prefab builder scales them
down. The app's Settings show the same icons in their mini guide to the menu:
small copies in assets/menu/ (APP_SIZE px), written from docs/unity/icons/
(only those, from the committed icons: add --app-only).
The icons are committed; re-run this after changing one:
    venv\\Scripts\\python.exe tools\\make_menu_icons.py [--sheet out.png]
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# offscreen Qt only finds fonts it is pointed at; without them the numbers
# and STOP come out as empty boxes
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR",
                          os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QImage,  # noqa: E402
                           QPainter, QPainterPath, QPen, QPolygonF)

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from ui.theme_tokens import PALETTE  # noqa: E402

OUT = REPO / "docs" / "unity" / "icons"
SIZE = 512
APP_OUT = REPO / "assets" / "menu"     # the copies the app's Settings guide shows
APP_SIZE = 96                          # 28 px at 100 % text, sharp up to 2x and 150 %
W = 28                     # the line width, as in OGP's set
WHITE = "#ffffff"
GREEN, RED = PALETTE["green"][0], PALETTE["red"][0]


def _pen(p: QPainter, color: str = WHITE, width: float = W) -> None:
    p.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)


def _fill(p: QPainter, color: str) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor(color)))


def _text(p: QPainter, rect: QRectF, text: str, color: str, size: int,
          weight=QFont.Black) -> None:
    f = QFont("Segoe UI", size)
    f.setWeight(weight)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(rect, Qt.AlignCenter, text)


# ---------------------------------------------------------------------------
# shapes reused by several icons
# ---------------------------------------------------------------------------

def _ruler(p: QPainter, x: float, y0: float, y1: float, ticks: int = 5,
           long: float = 72, short: float = 42) -> None:
    """The app icon's ruler: a white upright with ticks to the right,
    long and short in turn."""
    _pen(p)
    p.drawLine(QPointF(x, y0), QPointF(x, y1))
    for k in range(ticks):
        y = y0 + 14 + k * (y1 - y0 - 28) / (ticks - 1)
        p.drawLine(QPointF(x, y), QPointF(x + (long if k % 2 == 0 else short), y))


def _arrow(p: QPainter, x: float, y0: float, y1: float, color: str, head: float = 62,
           width: float = W * 1.25) -> None:
    """A vertical arrow from y0 to its tip at y1 (up when y1 < y0)."""
    _pen(p, color, width)
    p.drawLine(QPointF(x, y0), QPointF(x, y1))
    d = -1 if y1 < y0 else 1
    path = QPainterPath(QPointF(x - head, y1 - d * head))
    path.lineTo(QPointF(x, y1))
    path.lineTo(QPointF(x + head, y1 - d * head))
    p.drawPath(path)


def _stop(p: QPainter) -> None:
    """OGP's stop sign, unchanged."""
    pts = [(256 + 200 * math.cos(math.radians(22.5 + 45 * k)),
            256 + 200 * math.sin(math.radians(22.5 + 45 * k))) for k in range(8)]
    poly = QPolygonF([QPointF(x, y) for x, y in pts])
    _fill(p, RED)
    p.drawPolygon(poly)
    _pen(p, WHITE, 16)
    inner = QPolygonF([QPointF(256 + (x - 256) * 0.86, 256 + (y - 256) * 0.86) for x, y in pts])
    p.drawPolygon(inner)
    _text(p, QRectF(0, 0, SIZE, SIZE), "STOP", WHITE, 70)


def _numbered(p: QPainter, n: int, glyph) -> None:
    """OGP's numbered slot: the glyph, and a green badge bottom-right."""
    glyph(p)
    _fill(p, GREEN)
    p.drawEllipse(QPointF(380, 380), 104, 104)
    _text(p, QRectF(276, 276, 208, 208), str(n), "#000000", 120)


def _slot_tray(p: QPainter, dx: float = 0, dy: float = 0, s: float = 1.0) -> None:
    """A slot to keep a height in: an open tray, a green arrow going in."""
    p.save()
    p.translate(dx, dy)
    p.scale(s, s)
    _pen(p)
    tray = QPainterPath(QPointF(90, 250))
    tray.lineTo(QPointF(90, 420))
    tray.lineTo(QPointF(422, 420))
    tray.lineTo(QPointF(422, 250))
    p.drawPath(tray)
    _arrow(p, 256, 70, 330, GREEN)
    p.restore()


def _load_glyph(p: QPainter) -> None:
    """Load slot N: a green marker set against the ruler."""
    _ruler(p, 186, 60, 452)
    _fill(p, GREEN)
    p.drawPolygon(QPolygonF([QPointF(150, 160), QPointF(40, 96), QPointF(40, 224)]))


def _save_glyph(p: QPainter) -> None:
    """Save slot N: the current height goes into the slot."""
    _slot_tray(p, dx=-40, dy=-30, s=0.85)


# ---------------------------------------------------------------------------
# the icons
# ---------------------------------------------------------------------------

def grow(p):
    """Hold to grow: the app icon's arrow, pointing up only, by its ruler."""
    _arrow(p, 186, 452, 66, GREEN, head=84, width=W * 1.5)
    _ruler(p, 330, 60, 452)


def shrink(p):
    """Hold to shrink: the same, pointing down."""
    _arrow(p, 186, 60, 446, GREEN, head=84, width=W * 1.5)
    _ruler(p, 330, 60, 452)


def play_pause(p):
    """The slow transition: its rising curve in green, play and pause."""
    _pen(p, GREEN, W * 1.1)
    curve = QPainterPath(QPointF(60, 448))
    curve.cubicTo(QPointF(250, 446), QPointF(370, 420), QPointF(452, 330))
    p.drawPath(curve)
    _pen(p)
    tri = QPolygonF([QPointF(92, 64), QPointF(92, 284), QPointF(252, 174)])
    p.drawPolygon(tri)
    p.drawLine(QPointF(330, 66), QPointF(330, 282))
    p.drawLine(QPointF(420, 66), QPointF(420, 282))


def stop(p):
    _stop(p)


def saved(p):
    """Saved heights: four slots, each holding another height."""
    for (x, y), level in zip(((62, 62), (276, 62), (62, 276), (276, 276)),
                             (0.78, 0.56, 0.36, 0.18)):
        _fill(p, GREEN)
        inner = QRectF(x + 30, y + 30, 114, 114)
        top = inner.bottom() - inner.height() * level
        p.drawRoundedRect(QRectF(inner.left(), top, inner.width(), inner.bottom() - top), 12, 12)
        _pen(p)
        p.drawRoundedRect(QRectF(x, y, 174, 174), 30, 30)


def save(p):
    """Save the current height: into a slot."""
    _slot_tray(p)


def own_height(p):
    """Back to the avatar's own height: a green turn-back arrow by the ruler."""
    _pen(p, GREEN, W * 1.25)
    box = QRectF(56, 136, 240, 240)
    p.drawArc(box, 100 * 16, 290 * 16)
    # the arrowhead at the arc's open end (top), pointing back along it
    end = QPointF(box.center().x() + 120 * math.cos(math.radians(100)),
                  box.center().y() - 120 * math.sin(math.radians(100)))
    path = QPainterPath(QPointF(end.x() + 70, end.y() - 46))
    path.lineTo(end)
    path.lineTo(QPointF(end.x() + 62, end.y() + 58))
    p.drawPath(path)
    _ruler(p, 380, 60, 452, long=60, short=36)


def roll(p):
    """A random height: a die, its pips green (it changes your height)."""
    _pen(p)
    p.drawRoundedRect(QRectF(76, 76, 360, 360), 64, 64)
    _fill(p, GREEN)
    for x, y in ((166, 166), (256, 256), (346, 346), (346, 166), (166, 346)):
        p.drawEllipse(QPointF(x, y), 34, 34)


def pause_cards(p):
    """Pause the size parameter cards: two cards, the pause bars on top."""
    _pen(p)
    p.drawRoundedRect(QRectF(60, 120, 250, 320), 34, 34)
    back = QPainterPath(QPointF(150, 120))
    back.lineTo(QPointF(150, 96))
    back.arcTo(QRectF(150, 62, 68, 68), 180, -90)
    back.lineTo(QPointF(366, 62))
    back.arcTo(QRectF(332, 62, 68, 68), 90, -90)
    back.lineTo(QPointF(400, 340))
    back.lineTo(QPointF(310, 340))
    p.drawPath(back)
    _fill(p, WHITE)
    p.drawRoundedRect(QRectF(330, 300, 48, 160), 14, 14)
    p.drawRoundedRect(QRectF(410, 300, 48, 160), 14, 14)


ICONS = {
    "grow": grow, "shrink": shrink, "play_pause": play_pause, "stop": stop,
    "own_height": own_height, "roll": roll, "pause_cards": pause_cards,
    "saved": saved, "save": save,
}
for _n in range(1, 5):
    ICONS[f"load{_n}"] = (lambda n: lambda p: _numbered(p, n, _load_glyph))(_n)
    ICONS[f"save{_n}"] = (lambda n: lambda p: _numbered(p, n, _save_glyph))(_n)


def render(name: str) -> QImage:
    img = QImage(SIZE, SIZE, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    ICONS[name](p)
    p.end()
    return img


def app_copies() -> None:
    """assets/menu/<name>.png: each committed icon, smoothly scaled to
    APP_SIZE px, for the mini guide at the bottom of the app's Settings."""
    APP_OUT.mkdir(parents=True, exist_ok=True)
    names = ["menu"] + list(ICONS)
    for name in names:
        img = QImage(str(OUT / f"{name}.png"))
        if img.isNull():
            raise SystemExit(f"missing {OUT / name}.png")
        img.scaled(APP_SIZE, APP_SIZE, Qt.KeepAspectRatio,
                   Qt.SmoothTransformation).save(str(APP_OUT / f"{name}.png"))
    print(f"{len(names)} app copies in {APP_OUT}")


def main() -> None:
    QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    if "--app-only" in sys.argv:
        app_copies()
        return
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ICONS:
        render(name).save(str(OUT / f"{name}.png"))
    if "--sheet" in sys.argv:
        sheet_path = sys.argv[sys.argv.index("--sheet") + 1]
        names = list(ICONS)
        menu = OUT / "menu.png"
        cols, cell = 8, 150
        rows = (len(names) + 1 + cols - 1) // cols
        sheet = QImage(cols * cell, rows * (cell + 22), QImage.Format_ARGB32)
        sheet.fill(QColor(40, 44, 52))
        p = QPainter(sheet)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        tiles = ([("menu", QImage(str(menu)))] if menu.exists() else []) + \
                [(n, render(n)) for n in names]
        for i, (name, img) in enumerate(tiles):
            x, y = (i % cols) * cell, (i // cols) * (cell + 22)
            p.drawImage(QRectF(x + 15, y + 8, 120, 120), img)
            _text(p, QRectF(x, y + cell - 12, cell, 22), name, "#c8c8c8", 9, QFont.Normal)
        p.end()
        sheet.save(sheet_path)
    print(f"{len(ICONS)} icons in {OUT}")
    app_copies()


if __name__ == "__main__":
    main()
