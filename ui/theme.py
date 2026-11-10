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

TEXT_SCALES = (0.85, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0)

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
QLabel#HeroValue {
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 30px; font-weight: 600; color: %(txt)s;
}
QLabel#HeroValue[known="false"] { color: %(dim)s; font-size: 24px; }
QLabel#HeroSub { color: %(muted)s; font-size: 12px; }
QLabel#FieldLabel { color: %(muted)s; }
QLabel#RangeLabel { color: %(dim)s; font-size: 11px; }
QLabel#TransitionStatus { color: %(muted)s; font-size: 12px; }
QLabel#TransitionStatus[state="run"] { color: %(run)s; }
QLabel#TransitionStatus[state="warn"] { color: %(warn)s; }
QLabel#ProfileName { color: %(muted)s; }
QLabel#ProfileValue { font-family: "Cascadia Mono", Consolas, monospace; color: %(txt)s; }
QLabel#ProfileValue[empty="true"] { color: %(dim)s; }
QLabel#StatusMsg { color: %(muted)s; font-size: 11px; }
QLabel#IdentityTag { color: %(dim)s; font-size: 11px; }
QLabel#PortsLine { color: %(muted)s; font-size: 12px; }
QLabel#Chip { min-height: 20px; max-height: 20px; }

QPushButton#Step { padding: 6px 4px; min-width: 50px; }
QPushButton#Seg { padding: 5px 12px; }
QPushButton#Ghost { padding: 5px 10px; }
QPushButton#Icon { padding: 3px 9px; font-size: 15px; }
QPushButton#Small { padding: 3px 12px; }

QAbstractSpinBox { background: %(well)s; border: 1px solid %(line)s; border-radius: %(r_input)spx; padding: 5px 8px; }
QAbstractSpinBox:focus { border-color: %(accent)s; }
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
    return v


def app_qss() -> str:
    v = colors()
    qss = T.QSS_TEMPLATE % v + T._group_variants() + _EXTRA_QSS % v
    if abs(_scale - 1.0) > 1e-3:
        qss = _FONT_SIZE_RE.sub(
            lambda m: f"font-size: {max(8, round(float(m.group(1)) * _scale))}px", qss)
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


