"""The 518 look for HeightShift: theme state, the app stylesheet, fonts.

Colours come only from `theme_tokens.py` (copied verbatim from
`_hub\\design\\theme_tokens.py`); `app_qss()` adds this app's few extras on
top and scales every font size for the text-size control. The mode and text
size are module state, so every widget reads the same values; `apply_theme`
restyles the running app (no restart).
"""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, Optional

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from . import theme_tokens as T

# Neon's filled section bar (VRCDollySync / FFMPEG Studio `_NEON_CAT_BARS`
# green, as OscGoesPurrr's ui/theme.py uses it). Midnight uses tint + accent.
_NEON_SECTION_BAR = "#1c8a3d"
# Neon's frame tone per hue: the border column of VRCDollySync's
# _NEON_CAT_BARS (the Neon source design-518.md names), copied, not mixed.
_NEON_FRAMES = {"red": "#b04552", "blue": "#3b6ea3"}

TEXT_SCALES = (0.85, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0)

# How opaque the size comparison's TARGET shadow is (the accent at this alpha).
SHADOW_ALPHA = 0.26

# The project folder (fonts/, the icon), or PyInstaller's unpack folder.
_ROOT = getattr(sys, "_MEIPASS",
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_mode: str = T.DEFAULT_MODE
_scale: float = 1.0

# This app's additions to theme_tokens.qss(). Same %(token)s names.
_EXTRA_QSS = """
QWidget#Body, QWidget#WorkColumn, QWidget#SettingsInner { background: transparent; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QFrame#SettingsPanel { background: %(panel)s; border: none; border-left: 1px solid %(line)s; }
QLabel { background: transparent; }

QLabel#SectionTitle {
    background: %(catbar)s; color: %(catbar_text)s;
    font-size: 14px; font-weight: 700; padding: 4px 10px; border-radius: %(r_gh)spx;
}
QLabel#PanelTitle { color: %(accent)s; font-size: 14px; font-weight: 700; }
QFrame#Comparison { background: %(card)s; border: 1px solid %(line)s; border-radius: %(r_card)spx; }
QLabel#Micro { color: %(dim)s; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
QLabel#KeyNow { border: 2px solid %(accent)s; border-radius: 5px; background: transparent; }
QLabel#KeyTarget { border: none; border-radius: 5px; background: %(shadow)s; }
QLabel#HeroValue {
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 28px; font-weight: 600; color: %(txt)s;
}
QLabel#HeroValue[known="false"] { color: %(dim)s; font-size: 22px; }
QLabel#HeroSub { color: %(muted)s; font-size: 12px; }
QLabel#TargetValue {
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 22px; font-weight: 600; color: %(txt)s;
}
QLabel#TargetNote { color: %(muted)s; font-size: 12px; }
QLabel#TargetNote[state="run"] { color: %(run)s; }
QLabel#TargetNote[state="warn"] { color: %(warn)s; }
QLabel#RatioValue {
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 20px; font-weight: 600; color: %(accent)s;
}
QLabel#RatioValue[same="true"] { color: %(muted)s; }
QLabel#RatioValue[long="true"] { font-size: 15px; }
QLabel#RatioWord { color: %(dim)s; font-size: 12px; }
QLabel#FieldLabel { color: %(muted)s; }
QLabel#RangeLabel { color: %(dim)s; font-size: 11px; }
QLabel#TransitionStatus { color: %(muted)s; font-size: 12px; }
QLabel#TransitionStatus[state="run"] { color: %(run)s; }
QLabel#TransitionStatus[state="warn"] { color: %(warn)s; }
QLabel#StatusMsg { color: %(muted)s; font-size: 11px; }
QLabel#IdentityTag { color: %(dim)s; font-size: 11px; }
QLabel#PortsLine { color: %(muted)s; font-size: 12px; }
QLabel#MenuLinks { font-size: 12px; }
QPushButton#UpdateChip { background: %(upd_tint)s; border: 1px solid %(upd_mid)s; border-radius: 10px;
    padding: 0px 10px; color: %(upd)s; font-size: 11px; font-weight: 700; min-height: 20px; max-height: 20px; }
QPushButton#UpdateChip:hover { border-color: %(upd)s; }
QLabel#UpdateStatus { color: %(muted)s; font-size: 12px; }
QLabel#MenuGuideLine { color: %(muted)s; font-size: 12px; }
QLabel#Chip { min-height: 20px; max-height: 20px; }

QPushButton#Step { padding: 6px 10px; min-width: 50px; }
QPushButton#GoInstant { background: %(instant)s; border-color: %(instant)s; color: %(ink)s; font-weight: 650; }
QPushButton#GoInstant:hover { background: %(instant)s; border-color: %(txt)s; color: %(ink)s; }
QPushButton#GoInstant:disabled { background: transparent; border-color: %(instant_mid)s; color: %(dim)s; }
QPushButton#GoTimed { background: %(timed)s; border-color: %(timed)s; color: %(ink)s; font-weight: 650; }
QPushButton#GoTimed:hover { background: %(timed)s; border-color: %(txt)s; color: %(ink)s; }
QPushButton#GoTimed:disabled { background: transparent; border-color: %(timed_mid)s; color: %(dim)s; }
QFrame#Card[hue="timed"] { border-color: %(timed_line)s; }
QFrame#Card[hue="timed"] QLabel#SectionTitle { background: %(timed_bar)s; color: %(timed_bar_text)s; }
QFrame#Card[hue="timed"] QPushButton, QFrame#Card[hue="timed"] QAbstractSpinBox { border-color: %(timed_mid)s; }
QFrame#Card[hue="timed"] QPushButton:hover { background: %(timed_tint)s; border-color: %(timed)s; color: %(timed)s; }
QFrame#Card[hue="timed"] QPushButton:checked { background: %(timed_tint)s; border-color: %(timed)s; color: %(timed)s; }
QFrame#Card[hue="timed"] QAbstractSpinBox:focus { border-color: %(timed)s; }
QPushButton#Step[sign="plus"] { border-color: %(plus_frame)s; }
QPushButton#Step[sign="plus"]:hover { background: %(plus_tint)s; border-color: %(plus)s; color: %(plus)s; }
QPushButton#Step[sign="minus"] { border-color: %(minus_frame)s; }
QPushButton#Step[sign="minus"]:hover { background: %(minus_tint)s; border-color: %(minus)s; color: %(minus)s; }
QPushButton#Step[sign="plus"]:disabled { border-color: %(plus_mid)s; }
QPushButton#Step[sign="minus"]:disabled { border-color: %(minus_mid)s; }
QPushButton#Seg { padding: 5px 12px; min-height: 20px; max-height: 20px; }
QLineEdit#ScaleEdit {
    padding: 1px 5px; font-size: 13px; font-weight: 700; border-color: %(accent)s;
    min-height: 22px; max-height: 22px;
}
QLineEdit#ScaleEdit[bad="true"] { border-color: %(warn)s; }
QPushButton#Refresh { border-color: transparent; color: %(muted)s; font-size: 16px; padding: 0px 7px; }
QPushButton#Refresh:hover { border-color: %(line)s; color: %(accent)s; }
QPushButton#Ghost { padding: 5px 10px; }
QPushButton#Icon { padding: 3px 9px; font-size: 15px; }
QPushButton#Small { padding: 3px 12px; }
QPushButton#Slot { font-family: "Cascadia Mono", Consolas, monospace; padding: 5px 8px; text-align: left;
                   min-height: 20px; max-height: 20px; }
QPushButton#SlotSave { padding: 5px 7px; min-height: 20px; max-height: 20px; }

QAbstractSpinBox {
    background: %(well)s; border: 1px solid %(line)s; border-radius: %(r_input)spx; padding: 5px 8px;
    min-height: 20px; max-height: 20px;
}
QAbstractSpinBox:focus { border-color: %(accent)s; }
/* number fields keep their step arrows but show none (ui/widgets.py
   no_buttons: NoButtons breaks the text field under Qt 6.12) */
QAbstractSpinBox[arrows="hidden"]::up-button, QAbstractSpinBox[arrows="hidden"]::down-button {
    width: 0px; border: none; image: none; }
QAbstractSpinBox[arrows="hidden"]::up-arrow, QAbstractSpinBox[arrows="hidden"]::down-arrow {
    image: none; width: 0px; height: 0px; }
QFrame#Card[hue="timed"] QAbstractSpinBox { border: 1px solid %(timed_mid)s; }
QFrame#Card[hue="timed"] QAbstractSpinBox:focus { border: 1px solid %(timed)s; }
QAbstractSpinBox:disabled, QPushButton:disabled { color: %(dim)s; }
QPushButton#Primary:disabled { background: transparent; border-color: %(green_mid)s; color: %(dim)s; }
QPushButton:disabled { border-color: %(green_mid)s; }

QCheckBox { background: transparent; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid %(line)s; border-radius: 4px; background-color: %(well)s;
}
/* ticked: the frame with a smaller square inside, not one solid fill
   (design-518.md §5 Checkboxes). Same outer size: 10 + 2 x 3 padding. */
QCheckBox::indicator:checked {
    background-color: %(accent)s; border-color: %(accent)s;
    width: 10px; height: 10px; padding: 3px; background-clip: content;
}
QCheckBox::indicator:hover { border-color: %(accent)s; }

QSlider { background: transparent; border: none; }
QSlider::groove:horizontal {
    height: 6px; background: %(well)s; border: 1px solid %(line)s; border-radius: 4px;
}
QSlider::sub-page:horizontal { background: %(accent)s; border-radius: 3px; margin: 1px; }
QSlider::add-page:horizontal { background: transparent; }
QSlider::handle:horizontal {
    background: %(accent)s; width: 14px; height: 14px; margin: -4px 0; border-radius: 7px; border: none;
}
QSlider::handle:horizontal:hover { background: %(accent2)s; }
QSlider::sub-page:horizontal:disabled { background: %(green_mid)s; }
QSlider::handle:horizontal:disabled { background: %(green_mid)s; }
"""

_FONT_SIZE_RE = re.compile(r"font-size:\s*(\d+(?:\.\d+)?)px")
# heights pinned in px grow with the text too, or a pill / spin box clips it
_HEIGHT_RE = re.compile(r"(min-height|max-height):\s*(\d+(?:\.\d+)?)px")


def mode() -> str:
    return _mode


def text_scale() -> float:
    return _scale


def colors() -> Dict[str, str]:
    """The token dict for the mode in use (theme_tokens.qss_vars + extras)."""
    v = T.qss_vars(_mode)
    if _mode == "neon":
        v["catbar"], v["catbar_text"] = _NEON_SECTION_BAR, v["txt"]
    else:
        v["catbar"], v["catbar_text"] = v["tint"], v["accent"]
    neon = _mode == "neon"
    # Nudge now: grow in a red frame, shrink in a blue one (Blise's call,
    # 2026-11-11 — an exception to red = errors only, see ui-style.md). At
    # rest the frame wears the hue's frame tone, as every Neon frame does
    # (Midnight: its mid tone); hovered, the vibrant one.
    v["plus"], v["plus_mid"], v["plus_tint"] = T.PALETTE["red"]
    v["minus"], v["minus_mid"], v["minus_tint"] = T.PALETTE["blue"]
    v["plus_frame"] = _NEON_FRAMES["red"] if neon else v["plus_mid"]
    v["minus_frame"] = _NEON_FRAMES["blue"] if neon else v["minus_mid"]
    # Go instant: filled pink (Blise, 2026-11-11)
    v["instant"], v["instant_mid"], v["instant_tint"] = T.PALETTE["pink"]
    # The timed transition's yellow (Blise, 2026-11-11): Go timed, and its
    # card's frame, bar, chosen options and graph, so they read as one thing.
    # The hub's yellow has no Neon bar tone: Neon fills the bar with the
    # vibrant yellow itself (like the button), Midnight uses tint + vibrant.
    vib, mid, tint = T.PALETTE["yellow"]
    v["timed"], v["timed_mid"], v["timed_tint"] = vib, mid, tint
    if neon:
        v["timed_bar"], v["timed_bar_text"], v["timed_line"] = vib, v["ink"], vib
    else:
        v["timed_bar"], v["timed_bar_text"], v["timed_line"] = tint, vib, mid
    # the updater's orange (design-518.md: updaters, nags, pending installs)
    v["upd"], v["upd_mid"], v["upd_tint"] = T.PALETTE["orange"]
    # the size comparison's target shadow (ui/figure.py), for its colour key
    a = v["accent"].lstrip("#")
    v["shadow"] = (f"rgba({int(a[0:2], 16)}, {int(a[2:4], 16)}, {int(a[4:6], 16)}, "
                   f"{round(SHADOW_ALPHA * 255)})")
    return v


def app_qss() -> str:
    v = colors()
    qss = T.QSS_TEMPLATE % v + T._group_variants() + _EXTRA_QSS % v
    if abs(_scale - 1.0) > 1e-3:
        qss = _FONT_SIZE_RE.sub(
            lambda m: f"font-size: {max(8, round(float(m.group(1)) * _scale))}px", qss)
        qss = _HEIGHT_RE.sub(
            lambda m: f"{m.group(1)}: {round(float(m.group(2)) * _scale)}px", qss)
    return qss


def apply_theme(app: QApplication, mode_name: Optional[str] = None,
                scale: Optional[float] = None) -> None:
    """Restyle the running app — no restart (ui-style.md: appearance changes
    apply live)."""
    global _mode, _scale
    if mode_name is not None:
        _mode = T.LEGACY_MODE_ALIASES.get(mode_name, mode_name)
        if _mode not in T.MODES:
            _mode = T.DEFAULT_MODE
    if scale is not None:
        _scale = min(TEXT_SCALES[-1], max(TEXT_SCALES[0], float(scale)))
    app.setStyleSheet(app_qss())


def resource_path(rel: str) -> str:
    return os.path.join(_ROOT, rel)


def register_fonts() -> None:
    """The 518 title face (Aldrich, OFL). Falls back to Segoe UI if missing."""
    path = resource_path(os.path.join("fonts", "Aldrich-Regular.ttf"))
    if os.path.exists(path):
        QFontDatabase.addApplicationFont(path)


