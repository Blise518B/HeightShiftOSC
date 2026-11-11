"""Small building blocks the window is made of: layouts, labels, the card and
settings-group frames, a segmented choice, and the Ctrl+wheel text zoom.
No app logic here — only how things look and the signals they emit."""

from __future__ import annotations

import re
from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QValidator
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDoubleSpinBox,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from height_logic import format_height, parse_height


def restyle(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def save_icon(color: str, px: int):
    """An arrow going down into a tray (the VRChat menu's Save icon, small):
    (QIcon, its size). Drawn at twice the size for sharp edges."""
    px = max(10, int(px))
    big = px * 2
    pix = QPixmap(big, big)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), big * 0.11, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    u = big / 16.0
    tray = QPainterPath(QPointF(2 * u, 9 * u))
    tray.lineTo(QPointF(2 * u, 14 * u))
    tray.lineTo(QPointF(14 * u, 14 * u))
    tray.lineTo(QPointF(14 * u, 9 * u))
    p.drawPath(tray)
    p.drawLine(QPointF(8 * u, 1.5 * u), QPointF(8 * u, 10 * u))
    head = QPainterPath(QPointF(4.5 * u, 6.8 * u))
    head.lineTo(QPointF(8 * u, 10.3 * u))
    head.lineTo(QPointF(11.5 * u, 6.8 * u))
    p.drawPath(head)
    p.end()
    pix.setDevicePixelRatio(2.0)
    return QIcon(pix), px


def vbox(margin: int = 0, spacing: int = 6) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setContentsMargins(margin, margin, margin, margin)
    lay.setSpacing(spacing)
    return lay


def hbox(margin: int = 0, spacing: int = 6) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(margin, margin, margin, margin)
    lay.setSpacing(spacing)
    return lay


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def hint(text: str) -> QLabel:
    """The dim 11px line under every setting (design-518.md §5 Settings)."""
    lab = label(text, "Hint", wrap=True)
    lab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    return lab


def styled(widget: QWidget, name: str) -> QWidget:
    widget.setObjectName(name)
    widget.setAttribute(Qt.WA_StyledBackground, True)
    return widget


def card(title: str, trailing: Optional[QWidget] = None) -> Tuple[QFrame, QVBoxLayout]:
    """A card with its filled section bar spanning the row; a trailing button
    sits at the row's right edge, outside the bar (ui-style.md)."""
    card = QFrame()
    card.setObjectName("Card")
    lay = vbox(margin=12, spacing=8)
    card.setLayout(lay)
    bar_row = hbox(spacing=8)
    bar = label(title, "SectionTitle")
    bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    bar_row.addWidget(bar, 1)
    if trailing is not None:
        bar_row.addWidget(trailing)
    lay.addLayout(bar_row)
    return card, lay


def group(title: str, hue: str) -> Tuple[QFrame, QVBoxLayout]:
    """A settings category frame in its identity hue."""
    frame = QFrame()
    frame.setObjectName("Group")
    frame.setProperty("hue", hue)
    outer = vbox(margin=6, spacing=6)
    frame.setLayout(outer)
    header = styled(QWidget(), "GroupHeader")
    hl = hbox(margin=0, spacing=0)
    hl.setContentsMargins(10, 4, 10, 4)
    header.setLayout(hl)
    hl.addWidget(label(title, "GroupTitle"))
    outer.addWidget(header)
    body = vbox(spacing=4)
    body.setContentsMargins(6, 2, 6, 6)
    outer.addLayout(body)
    return frame, body


def no_buttons(spin: QAbstractSpinBox) -> QAbstractSpinBox:
    """A number field without step arrows.

    Not QAbstractSpinBox.NoButtons: under Qt 6.12 a spin box with NoButtons
    and a stylesheet border or padding gets a 1 px wide text field — no
    number shown, nothing can be typed (HeightShift 2.0.20, built with
    PySide6 6.12.0). So the arrows stay, and the stylesheet folds them to
    nothing (QAbstractSpinBox[arrows="hidden"] in ui/theme.py)."""
    spin.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
    spin.setProperty("arrows", "hidden")
    spin.setKeyboardTracking(False)   # commit on Enter / leaving the field
    spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return spin


class HeightSpinBox(QDoubleSpinBox):
    """A height field that reads like the rest of the app — 170 cm, 12.5 m,
    1.25 km — and takes the same when typed (a bare number is cm; a decimal
    comma works too). A height outside the field's range is never clamped
    into it: the text stays unaccepted and the old value comes back."""

    _PARTIAL = re.compile(r"[0-9.,\s]*(c|cm|m|k|km)?\s*")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDecimals(1)
        self.setStepType(QAbstractSpinBox.AdaptiveDecimalStepType)

    def textFromValue(self, value: float) -> str:  # noqa: N802
        return format_height(value)

    def valueFromText(self, text: str) -> float:  # noqa: N802
        value = parse_height(text)
        return self.value() if value is None else value

    def validate(self, text: str, pos: int):
        value = parse_height(text)
        if value is not None and self.minimum() <= value <= self.maximum():
            return QValidator.Acceptable, text, pos
        if self._PARTIAL.fullmatch(text.lower()) or value is not None:
            return QValidator.Intermediate, text, pos
        return QValidator.Invalid, text, pos


class Segmented(QWidget):
    """A few mutually exclusive choices as buttons (one click, no dropdown)."""

    changed = Signal(str)

    def __init__(self, choices, parent=None):
        super().__init__(parent)
        lay = hbox(spacing=4)
        self.setLayout(lay)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: Dict[str, QPushButton] = {}
        for key, text in choices:
            btn = QPushButton(text)
            btn.setObjectName("Seg")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            self._group.addButton(btn)
            self._buttons[key] = btn
            lay.addWidget(btn)
            btn.clicked.connect(lambda _c=False, k=key: self.changed.emit(k))

    def set_tooltips(self, tips: Dict[str, str]) -> None:
        for key, tip in tips.items():
            if key in self._buttons:
                self._buttons[key].setToolTip(tip)

    def value(self) -> str:
        for key, btn in self._buttons.items():
            if btn.isChecked():
                return key
        return next(iter(self._buttons))

    def set_value(self, key: str) -> None:
        btn = self._buttons.get(key)
        if btn is not None:
            btn.setChecked(True)


_MODIFIER_QT_KEYS = (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr,
                     Qt.Key_CapsLock, Qt.Key_NumLock, Qt.Key_ScrollLock)


class KeyCaptureButton(QPushButton):
    """Shows a key; click it, then press the key (with Ctrl / Shift / Alt if
    wanted) to change it. Esc or clicking elsewhere cancels.

    Emits the Windows virtual-key code and MOD_CTRL 1 | MOD_SHIFT 2 | MOD_ALT 4
    — what hotkeys.Hotkey stores. `capturing` lets the owner pause the hotkeys
    themselves meanwhile, so setting a key doesn't also fire it."""

    captured = Signal(int, int)      # vk, mods
    capturing_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Small")
        self.setCursor(Qt.PointingHandCursor)
        self.capturing = False
        self._key_text = ""
        self.clicked.connect(self._start)

    def set_key_text(self, text: str) -> None:
        self._key_text = text
        if not self.capturing:
            self.setText(text)

    def _start(self) -> None:
        if self.capturing:
            return
        self.capturing = True
        self.setText("press a key…")
        self.grabKeyboard()
        self.capturing_changed.emit(True)

    def _stop(self) -> None:
        if not self.capturing:
            return
        self.releaseKeyboard()
        self.capturing = False
        self.setText(self._key_text)
        self.capturing_changed.emit(False)

    def keyPressEvent(self, event):  # noqa: N802
        if not self.capturing:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key_Escape:
            self._stop()
            return
        vk = int(event.nativeVirtualKey())
        if event.key() in _MODIFIER_QT_KEYS or not vk:
            return                    # a modifier alone: wait for the real key
        held = event.modifiers()
        mods = ((1 if held & Qt.ControlModifier else 0)
                | (2 if held & Qt.ShiftModifier else 0)
                | (4 if held & Qt.AltModifier else 0))
        self._stop()
        self.captured.emit(vk, mods)

    def focusOutEvent(self, event):  # noqa: N802
        self._stop()
        super().focusOutEvent(event)


class CtrlWheelZoom(QObject):
    """Ctrl + mouse wheel anywhere in `window` calls `on_step(+1 / -1)` (the
    text size). Installed after the wheel guard, so it sees the event first."""

    def __init__(self, window: QWidget, on_step: Callable[[int], None]):
        super().__init__(window)
        self._window = window
        self._on_step = on_step

    def eventFilter(self, obj, event):  # noqa: N802
        if (event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier
                and isinstance(obj, QWidget) and obj.window() is self._window):
            dy = event.angleDelta().y()
            if dy:
                self._on_step(1 if dy > 0 else -1)
            return True
        return False
