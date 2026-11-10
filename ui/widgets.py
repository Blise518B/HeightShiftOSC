"""Small building blocks the window is made of: layouts, labels, the card and
settings-group frames, a segmented choice, and the Ctrl+wheel text zoom.
No app logic here — only how things look and the signals they emit."""

from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def restyle(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


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
    spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    spin.setKeyboardTracking(False)   # commit on Enter / leaving the field
    spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return spin


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
