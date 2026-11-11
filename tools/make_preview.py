"""Draw the showcase pictures from the app itself.

    venv\\Scripts\\python.exe tools\\make_preview.py

writes
  docs/preview.png      2400 x 1260  the README's picture: what HeightShift
                                     does, the window, What's new, the menu
  docs/site/og.png      1200 x 630   the same, for link previews (og:image)
  docs/site/app.png     the window alone, for the website's headline

Everything in them is rendered by the app (the real window, the real
What's new, the VRChat menu's own icons), through the controller with a
fake VRChat, at 2x. Colours and fonts are the 518 tokens. Re-run it when
the window changes.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")      # real glyphs, real fonts
os.environ.setdefault("QT_SCREEN_SCALE_FACTORS", "2;2;2;2")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QImage, QMouseEvent, QPainter, QPainterPath,  # noqa: E402
                           QPen, QRadialGradient)
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from tests.test_controller import FakeConsole, FakeKeys, FakeOSC, FakeRouter, Clock, _app  # noqa: E402
import controller  # noqa: E402
import whats_new  # noqa: E402
from config_manager import ConfigManager  # noqa: E402
from ui import theme  # noqa: E402
from ui import theme_tokens as T  # noqa: E402
from ui.window import HeightShiftWindow  # noqa: E402

W, H = 2400, 1260          # the README picture; og.png is it at half size
# The window, tall enough for the Size parameters card under the timed
# transition, wide enough for three of its cards in a row.
WIN_W, WIN_H = 1000, 1240


def render_window():
    """The window as it is used: you at 1.7 m, a 50 m target, saved heights
    in all three colours, the scale on Go instant, the mouse over 12 m, and
    size parameter cards — a headpat growing you, a 🎲 card."""
    theme.register_fonts()
    controller.VRChatOSCManager = FakeOSC
    controller.Router518KeepAlive = FakeRouter
    controller.KeyReader = FakeKeys
    clock = Clock()
    controller.now = clock
    theme.apply_theme(_app, mode_name="neon", scale=1.0)
    cfg = ConfigManager(os.path.join(tempfile.mkdtemp(), "c.json"))
    cfg.update_config({
        "settings_open": False, "transition_target_cm": 5000, "transition_duration": 20,
        "transition_unit": "s", "transition_curve": "scale", "scale_mode": "instant",
        "profiles": {"profile1": 140.0, "profile2": 1.0, "profile3": 5000.0,
                     "profile4": 3.0, "profile5": 300.0},
        "profile_actions": {"profile2": "instant", "profile3": "timed",
                            "profile4": "instant", "profile5": "timed"},
        "size_params": [
            {"kind": "param", "param": "HeightShift/Contact/Grow", "type": "Bool",
             "dir": "grow", "speed": 5.0, "unit": "cm"},
            {"kind": "param", "param": "Contacts/FootOnHead", "type": "Float",
             "dir": "shrink", "speed": 2.5, "unit": "pct"},
            {"kind": "random", "param": "HeightShift/Contact/Random", "type": "Bool",
             "min": 30.0, "max": 1000.0, "go": "timed"}]})
    win = HeightShiftWindow("v2.0", "2.0")
    ctl = controller.HeightShiftController(win, cfg, FakeConsole())
    win.resize(WIN_W, WIN_H)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    ctl.osc.is_connected = True
    ctl._on_connected()
    ctl._on_reported(1.70, clock.t)
    ctl._on_params_read(ctl._params_round, {
        "HeightShift/Contact/Grow": ("Bool", False), "Contacts/FootOnHead": ("Float", 0.0),
        "HeightShift/Contact/Random": ("Bool", False)})
    ctl._on_param("HeightShift/Contact/Grow", True, clock.t)     # a headpat, right now
    ctl._last_roll[ctl.size_params[2]["id"]] = 312.0
    ctl._show_param_live()
    ctl._param_timer.stop()
    for _ in range(6):
        _app.processEvents()
    fig = win.figure
    fig.snap()
    pt = QPoint(round(fig.axis_x()), round(fig.y_of(1200.0)))
    QApplication.sendEvent(fig, QMouseEvent(QEvent.MouseMove, QPointF(pt),
                                            QPointF(fig.mapToGlobal(pt)), Qt.NoButton,
                                            Qt.NoButton, Qt.NoModifier))
    for _ in range(3):
        _app.processEvents()
    shot = win.grab()
    win.show_whats_new(whats_new.as_plain(whats_new.RELEASES[:1]))
    news = win.whats_new_dialog
    for _ in range(3):
        _app.processEvents()
    news_shot = news.grab()
    news.accept()
    return shot, news_shot


def rounded(p: QPainter, img: QImage, rect: QRectF, radius: float, border: str) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.save()
    p.setClipPath(path)
    p.drawImage(rect, img)
    p.restore()
    p.setPen(QPen(QColor(border), 3))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)


def font(family: str, px: int, bold: bool = False) -> QFont:
    f = QFont(family)
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def compose(window_img: QImage, news_img: QImage) -> QImage:
    c = theme.colors()
    pal = T.PALETTE
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(QColor(c["bg"]))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setRenderHint(QPainter.TextAntialiasing)

    glow = QRadialGradient(QPointF(W * 0.42, -120), W * 0.6)
    accent = QColor(c["accent"])
    accent.setAlpha(40)
    glow.setColorAt(0.0, accent)
    glow.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.fillRect(img.rect(), glow)

    # --- left: what it is -------------------------------------------------
    x, y = 90, 110
    icon = QImage(str(ROOT / "docs" / "unity" / "icons" / "menu.png"))
    p.drawImage(QRectF(x, y, 112, 112), icon)
    p.setFont(font("Aldrich", 82))
    p.setPen(QColor(c["accent"]))
    p.drawText(QRectF(x + 138, y, 700, 112), Qt.AlignVCenter | Qt.AlignLeft, "HeightShift")
    y += 160
    p.setFont(font("Segoe UI", 44, bold=True))
    p.setPen(QColor(c["txt"]))
    p.drawText(QRectF(x, y, 700, 130), Qt.AlignLeft | Qt.TextWordWrap,
               "Change your height in VRChat, smoothly.")
    y += 150
    features = (
        (pal["green"][0], "Your height and the target on one picture"),
        (pal["pink"][0], "Go instant — there at once"),
        (pal["yellow"][0], "Go timed — over seconds, minutes or hours"),
        (pal["cyan"][0], "A headpat grows you: avatar parameters"),
        (pal["cyan"][0], "🎲 Random heights, a roll away"),
        (pal["green"][0], "Nine saved heights on numpad 1–9"),
        (pal["red"][0], "Nudge ±1 / 10 / 100 cm, or hold a key"),
        (pal["amber"][0], "A menu in VRChat (VRCFury prefab)"),
    )
    p.setFont(font("Segoe UI", 31))
    for colour, text in features:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(colour))
        p.drawEllipse(QPointF(x + 11, y + 26), 10, 10)
        p.setPen(QColor(c["txt"]))
        p.drawText(QRectF(x + 40, y, 690, 52), Qt.AlignVCenter | Qt.AlignLeft, text)
        y += 68
    p.setFont(font("Segoe UI", 27))
    p.setPen(QColor(c["muted"]))
    p.drawText(QRectF(x, H - 150, 720, 80), Qt.AlignLeft | Qt.TextWordWrap,
               "Free for Windows · one file, no install\nblise518b.github.io/HeightShiftOSC")

    # --- middle: the window ---------------------------------------------------
    win_h = H - 2 * 70
    win_w = round(win_h * window_img.width() / window_img.height())
    wx = 820
    rounded(p, window_img, QRectF(wx, 70, win_w, win_h), 18, c["line"])

    # --- right: the VRChat menu, then What's new -----------------------------
    rx = wx + win_w + 50
    rw = W - rx - 70
    p.setFont(font("Segoe UI", 28, bold=True))
    p.setPen(QColor(c["muted"]))
    p.drawText(QRectF(rx, 70, rw, 44), Qt.AlignLeft | Qt.AlignVCenter, "In your Action Menu")
    my = 130
    menu = (("grow", "Grow"), ("shrink", "Shrink"), ("play_pause", "Play"),
            ("stop", "Stop"), ("own_height", "Own height"), ("roll", "Random"),
            ("pause_cards", "Pause cards"), ("load1", "Load"), ("save1", "Save"))
    cols, gap = 3, 18
    cell = (rw - (cols - 1) * gap) / cols
    p.setFont(font("Segoe UI", 22, bold=True))
    for i, (name, text) in enumerate(menu):
        cx = rx + (i % cols) * (cell + gap)
        cy = my + (i // cols) * (cell + 46)
        box = QRectF(cx, cy, cell, cell)
        p.setPen(QPen(QColor(pal["amber"][1]), 3))
        p.setBrush(QColor(c["card"]))
        p.drawRoundedRect(box, 16, 16)
        pic = QImage(str(ROOT / "docs" / "unity" / "icons" / f"{name}.png"))
        p.drawImage(box.adjusted(cell * 0.16, cell * 0.16, -cell * 0.16, -cell * 0.16), pic)
        p.setPen(QColor(c["txt"]))
        p.drawText(QRectF(cx - gap / 2, cy + cell + 2, cell + gap, 38), Qt.AlignCenter, text)

    ny = my + 3 * (cell + 46) + 30
    p.setFont(font("Segoe UI", 28, bold=True))
    p.setPen(QColor(c["muted"]))
    p.drawText(QRectF(rx, ny, rw, 44), Qt.AlignLeft | Qt.AlignVCenter, "After each update")
    ny += 56
    room = H - 70 - ny
    nw = min(rw, room * news_img.width() / news_img.height())
    nh = nw * news_img.height() / news_img.width()
    rounded(p, news_img, QRectF(rx, ny, nw, nh), 14, pal["orange"][1])
    p.end()
    return img


def main() -> None:
    window_pix, news_pix = render_window()
    window_img, news_img = window_pix.toImage(), news_pix.toImage()
    sheet = compose(window_img, news_img)
    sheet.save(str(ROOT / "docs" / "preview.png"))
    sheet.scaled(W // 2, H // 2, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).save(
        str(ROOT / "docs" / "site" / "og.png"))
    window_img.save(str(ROOT / "docs" / "site" / "app.png"))
    print("docs/preview.png", sheet.width(), sheet.height(), "| docs/site/app.png",
          window_img.width(), window_img.height())


if __name__ == "__main__":
    main()
