"""
The Size parameters card's pieces (ui/window.py builds the card around them).

  * ParamCard — an avatar parameter that grows or shrinks you while it is
    on: which one, which way, how fast, its own ⏸ / ▶, and a line saying
    what it does right now.
  * RandomCard — a random height between two, on 🎲 or when a parameter
    turns on; then select it, go instant or go timed (the saved heights'
    three actions, in their colours).
  * CardBoard — the cards left to right, wrapping (OscGoesPurrr's Avatar
    Remote board): drag one by its ⠿ to sort it; a parameter dropped on free
    room makes a new card there. A see-through copy shows where it lands.
  * ParamPicker — the avatar's parameters, beside the window (OGP's list):
    filter, click one to use it, or drag it onto a card.

Pure view, like the window: signals out, setters in.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QEvent, QMimeData, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDoubleSpinBox,
    QFrame,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
    QWidgetItem,
)

from constants import HOTKEY_SPEED_MIN, MIN_HEIGHT_CM
from height_logic import (KIND_PARAM, KIND_RANDOM, PARAM_GROW, PARAM_SHRINK, SPEED_CM,
                          SPEED_PERCENT, speed_max)

from .widgets import HeightSpinBox, Segmented, hbox, hint, label, no_buttons, restyle, vbox

CARD_W = 300                    # a card's width at 100 % text
PICKER_W = 340                  # the parameter list's
MIME_PARAM = "application/x-heightshift-param"   # "name\ntype": a row of the list
MIME_CARD = "application/x-heightshift-card"     # a card's id: sorted

# A drag never leaves the app: the see-through copy of what is dragged
# travels through here to the board it is dragged over.
_GHOST: Optional[QPixmap] = None


def _faded(widget: QWidget) -> QPixmap:
    source = widget.grab()
    pix = QPixmap(source.size())
    pix.setDevicePixelRatio(source.devicePixelRatio())
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setOpacity(0.55)
    painter.drawPixmap(0, 0, source)
    painter.end()
    return pix


def value_text(value: Any) -> str:
    if value is None:
        return "–"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


class FlowLayout(QLayout):
    """Left to right, wrapping (the Qt flow layout example, OGP's BoardFlow):
    a hidden card (one being dragged) takes no room."""

    def __init__(self, parent: Optional[QWidget] = None, spacing: int = 10):
        super().__init__(parent)
        self._items: List[QWidgetItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self._gap = spacing

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def insert_widget(self, index: int, widget: QWidget) -> None:
        self.addWidget(widget)
        self._items.insert(max(0, min(index, len(self._items) - 1)), self._items.pop())
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, dry=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, dry: bool) -> int:
        x, y = rect.x(), rect.y()
        line_h = 0
        for item in self._items:
            if item.isEmpty():
                continue
            hint_ = item.sizeHint()
            if x + hint_.width() > rect.right() + 1 and line_h > 0:
                x = rect.x()
                y += line_h + self._gap
                line_h = 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), hint_))
            x += hint_.width() + self._gap
            line_h = max(line_h, hint_.height())
        return y + line_h - rect.y()


class ElideButton(QPushButton):
    """A button whose text is cut at the start when it doesn't fit: the end
    of a parameter's name is what tells two apart (…Contact/Grow)."""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        room = max(20, self.width() - 22)
        super().setText(QFontMetrics(self.font()).elidedText(self._full, Qt.ElideLeft, room))


# ----------------------------------------------------------------------
# The cards
# ----------------------------------------------------------------------

class SizeCard(QFrame):
    """What both cards share: the ⠿ grip, the card's own ⏸ / ▶, ✕, the
    line at the bottom, and taking a parameter dropped on it."""

    changed = Signal(str, object)     # card id, {field: value}
    removed = Signal(str)
    pick = Signal(str)                # wants a parameter from the list

    def __init__(self, entry: Dict[str, Any]) -> None:
        super().__init__()
        self.pid = entry["id"]
        self.entry = dict(entry)
        self._quiet = False
        self._press: Optional[QPoint] = None
        self.retired = False              # replaced by a rebuild: never shown again
        self.setObjectName("SizeCard")
        self.setProperty("kind", entry.get("kind", KIND_PARAM))
        self.setProperty("picking", "false")
        self.setAcceptDrops(True)
        self.lay = vbox(margin=10, spacing=6)
        self.setLayout(self.lay)
        self.head = hbox(spacing=6)
        self.lay.addLayout(self.head)
        self.grip = QLabel("⠿")
        self.grip.setObjectName("CardGrip")
        self.grip.setCursor(Qt.OpenHandCursor)
        self.grip.setToolTip("Drag to sort the cards")
        self.grip.installEventFilter(self)
        self.head.addWidget(self.grip)
        self.on_btn = QPushButton()
        self.on_btn.setObjectName("CardToggle")
        self.on_btn.setCheckable(True)
        self.on_btn.setCursor(Qt.PointingHandCursor)
        self.on_btn.clicked.connect(self._on_toggle)
        self.head.addWidget(self.on_btn)
        self.remove_btn = QPushButton("✕")
        self.remove_btn.setObjectName("CardRemove")
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.setToolTip("Remove this card")
        self.remove_btn.clicked.connect(lambda: self.removed.emit(self.pid))
        self.live = label("", "CardLive", wrap=True)
        self.live.setMinimumWidth(1)

    def finish(self) -> None:
        """After the subclass added its rows: ✕ last in the head, the line
        last in the card."""
        self.head.addWidget(self.remove_btn)
        self.lay.addWidget(self.live)
        self.set_entry(self.entry)

    # --- state --------------------------------------------------------------

    def set_entry(self, entry: Dict[str, Any]) -> None:
        self.entry = dict(entry)
        on = bool(entry.get("on", True))
        self.on_btn.setChecked(on)
        # ‖ / ▶ as text: ⏸ draws as a coloured emoji
        self.on_btn.setText("‖" if on else "▶")
        self.on_btn.setToolTip("On — click to pause this card" if on
                               else "Paused — click to switch it back on")
        self.on_btn.setProperty("on", "true" if on else "false")
        restyle(self.on_btn)

    def set_live(self, text: str, state: str) -> None:
        if self.live.text() != text:
            self.live.setText(text)
        if self.live.property("state") != state:
            self.live.setProperty("state", state)
            restyle(self.live)

    def set_picking(self, on: bool) -> None:
        self.setProperty("picking", "true" if on else "false")
        restyle(self)

    def _emit(self, changes: Dict[str, Any]) -> None:
        if not self._quiet:
            self.changed.emit(self.pid, changes)

    def _on_toggle(self, checked: bool) -> None:
        self.set_entry({**self.entry, "on": bool(checked)})
        self._emit({"on": bool(checked)})

    # --- dragging it by its grip --------------------------------------------

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.grip:
            kind = event.type()
            if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._press = event.position().toPoint()
                return True
            if kind == QEvent.MouseMove and self._press is not None:
                if ((event.position().toPoint() - self._press).manhattanLength()
                        >= QApplication.startDragDistance()):
                    self._press = None
                    self._drag()
                return True
            if kind == QEvent.MouseButtonRelease:
                self._press = None
        return super().eventFilter(obj, event)

    def _drag(self) -> None:
        global _GHOST
        pix = self.grab()
        _GHOST = _faded(self)
        mime = QMimeData()
        mime.setData(MIME_CARD, self.pid.encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(pix)
        drag.setHotSpot(QPoint(16, 16))
        self.hide()                       # takes no room while it is carried
        drag.exec(Qt.MoveAction)
        _GHOST = None
        try:
            if not self.retired:          # the drop rebuilt the cards: this one is gone
                self.show()
        except RuntimeError:
            pass

    # --- a parameter from the list dropped on it ------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME_PARAM):
            event.acceptProposedAction()
            self.set_picking(True)
        else:
            event.ignore()                # a card being sorted: the board's

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME_PARAM):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.set_picking(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.set_picking(False)
        md = event.mimeData()
        if not md.hasFormat(MIME_PARAM):
            event.ignore()
            return
        name, _sep, ptype = bytes(md.data(MIME_PARAM)).decode().partition("\n")
        event.acceptProposedAction()
        self.changed.emit(self.pid, {"param": name, "type": ptype})


class ParamCard(SizeCard):
    """An avatar parameter that grows or shrinks you: a Bool at the full
    speed while on, a Float at its share (0–1) of it, an Int while not 0."""

    def __init__(self, entry: Dict[str, Any]) -> None:
        super().__init__(entry)
        self.name_btn = ElideButton()
        self.name_btn.setObjectName("ParamName")
        self.name_btn.setCursor(Qt.PointingHandCursor)
        self.name_btn.clicked.connect(lambda: self.pick.emit(self.pid))
        self.head.addWidget(self.name_btn, 1)
        self.type_lbl = label("", "CardType")
        self.head.addWidget(self.type_lbl)

        row = hbox(spacing=6)
        self.dir_seg = Segmented([(PARAM_GROW, "Grow"), (PARAM_SHRINK, "Shrink")])
        self.dir_seg.mark_kinds()
        self.dir_seg.set_tooltips({PARAM_GROW: "Grow while it is on",
                                   PARAM_SHRINK: "Shrink while it is on"})
        self.dir_seg.changed.connect(lambda k: self._emit({"dir": k}))
        row.addWidget(self.dir_seg)
        self.speed_spin = no_buttons(QDoubleSpinBox())
        self.speed_spin.setDecimals(1)
        self.speed_spin.setMinimum(HOTKEY_SPEED_MIN)
        self.speed_spin.setMinimumWidth(62)
        self.speed_spin.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.speed_spin.setToolTip("How fast at full strength: a Bool that is on, a Float at 1")
        self.speed_spin.valueChanged.connect(lambda v: self._emit({"speed": float(v)}))
        row.addWidget(self.speed_spin, 1)
        self.unit_seg = Segmented([(SPEED_CM, "cm/s"), (SPEED_PERCENT, "%/s")])
        self.unit_seg.set_tooltips({
            SPEED_CM: "The same number of centimetres every second",
            SPEED_PERCENT: "The same share of your height every second: feels the same at "
                           "30 cm and at 50 m"})
        self.unit_seg.changed.connect(self._on_unit)
        row.addWidget(self.unit_seg)
        self.lay.addLayout(row)
        self.finish()

    def set_entry(self, entry: Dict[str, Any]) -> None:
        super().set_entry(entry)
        self._quiet = True
        try:
            name = entry.get("param") or ""
            self.name_btn.set_full_text(name or "Pick a parameter…")
            self.name_btn.setProperty("empty", "false" if name else "true")
            restyle(self.name_btn)
            self.name_btn.setToolTip(
                (f"{name} — click to pick another" if name
                 else "Pick the avatar parameter from the list beside the window"))
            self.type_lbl.setText((entry.get("type") or "").upper())
            self.dir_seg.set_value(entry.get("dir", PARAM_GROW))
            unit = entry.get("unit", SPEED_CM)
            self.unit_seg.set_value(unit)
            self.speed_spin.setMaximum(speed_max(unit))
            self.speed_spin.setValue(float(entry.get("speed", 5.0)))
        finally:
            self._quiet = False

    def _on_unit(self, unit: str) -> None:
        self._quiet = True
        try:
            self.speed_spin.setMaximum(speed_max(unit))
        finally:
            self._quiet = False
        self._emit({"unit": unit, "speed": float(self.speed_spin.value())})


class RandomCard(SizeCard):
    """A random height between two (even on the height scale: 1–10 m as
    likely as 10–100 m), on 🎲 or when its parameter turns on."""

    roll = Signal(str)

    ACTIONS = (("select", "Select"), ("instant", "Go instant"), ("timed", "Go timed"))

    def __init__(self, entry: Dict[str, Any], top_cm: float) -> None:
        super().__init__(entry)
        title = label("🎲  Random height", "CardTitle")
        self.head.addWidget(title, 1)

        rng = hbox(spacing=6)
        rng.addWidget(label("From", "FieldLabel"))
        self.lo_spin = no_buttons(HeightSpinBox())
        self.hi_spin = no_buttons(HeightSpinBox())
        for spin, key in ((self.lo_spin, "min"), (self.hi_spin, "max")):
            spin.setRange(MIN_HEIGHT_CM, top_cm)
            spin.setMinimumWidth(56)
            spin.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            spin.valueChanged.connect(lambda v, k=key: self._emit({k: float(v)}))
        rng.addWidget(self.lo_spin, 1)
        rng.addWidget(label("to", "FieldLabel"))
        rng.addWidget(self.hi_spin, 1)
        self.lay.addLayout(rng)

        self.go_seg = Segmented(list(self.ACTIONS))
        self.go_seg.mark_kinds()
        self.go_seg.set_tooltips({
            "select": "Only make it the target: Go instant or Go timed takes you there",
            "instant": "Go there at once",
            "timed": "Go there over the Timed transition's time"})
        self.go_seg.changed.connect(lambda k: self._emit({"go": k}))
        self.lay.addWidget(self.go_seg)

        row = hbox(spacing=6)
        self.roll_btn = QPushButton("🎲  Roll")
        self.roll_btn.setObjectName("Roll")
        self.roll_btn.setCursor(Qt.PointingHandCursor)
        self.roll_btn.setToolTip("Pick a random height now")
        self.roll_btn.clicked.connect(lambda: self.roll.emit(self.pid))
        row.addWidget(self.roll_btn)
        self.trigger_btn = ElideButton()
        self.trigger_btn.setObjectName("ParamName")
        self.trigger_btn.setCursor(Qt.PointingHandCursor)
        self.trigger_btn.clicked.connect(lambda: self.pick.emit(self.pid))
        row.addWidget(self.trigger_btn, 1)
        self.clear_btn = QPushButton("✕")
        self.clear_btn.setObjectName("CardRemove")
        self.clear_btn.setToolTip("No trigger: only 🎲 rolls")
        self.clear_btn.clicked.connect(lambda: self._emit({"param": "", "type": ""}))
        row.addWidget(self.clear_btn)
        self.lay.addLayout(row)
        self.finish()

    def set_top(self, top_cm: float) -> None:
        self._quiet = True
        try:
            for spin in (self.lo_spin, self.hi_spin):
                spin.setMaximum(top_cm)
        finally:
            self._quiet = False

    def set_entry(self, entry: Dict[str, Any]) -> None:
        super().set_entry(entry)
        self.on_btn.setToolTip("On — its trigger rolls; click to pause it (🎲 still works)"
                               if entry.get("on", True)
                               else "Paused: its trigger does nothing — click to switch it on")
        self._quiet = True
        try:
            self.lo_spin.setValue(float(entry.get("min", 50.0)))
            self.hi_spin.setValue(float(entry.get("max", 500.0)))
            self.go_seg.set_value(entry.get("go", "instant"))
            name = entry.get("param") or ""
            self.trigger_btn.set_full_text(name or "Trigger: pick a parameter…")
            self.trigger_btn.setProperty("empty", "false" if name else "true")
            restyle(self.trigger_btn)
            self.trigger_btn.setToolTip(
                (f"Rolls when {name} turns on — click to pick another" if name else
                 "Optional: an avatar parameter that rolls when it turns on (a contact, "
                 "a button)"))
            self.clear_btn.setVisible(bool(name))
        finally:
            self._quiet = False


# ----------------------------------------------------------------------
# The board
# ----------------------------------------------------------------------

class CardBoard(QWidget):
    """The cards, wrapping. Sorting a card and dropping a parameter on free
    room both show a see-through copy where it will land."""

    moved = Signal(str, int)               # card id, its new place
    param_dropped = Signal(str, str, int)  # name, type, place: a new card

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.flow = FlowLayout(self, spacing=10)
        self.cards: Dict[str, SizeCard] = {}
        self._ghost: Optional[QLabel] = None
        self._ghost_at = -1
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    def set_cards(self, cards: List[SizeCard]) -> None:
        self._remove_ghost()
        while self.flow.count():
            item = self.flow.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                if isinstance(widget, SizeCard):
                    widget.retired = True
                widget.hide()
                widget.deleteLater()
        self.cards = {}
        for card in cards:
            self.flow.addWidget(card)
            self.cards[card.pid] = card
        self.flow.invalidate()
        self.updateGeometry()

    # --- where a drop lands ---------------------------------------------------

    def _index_at(self, pos: QPoint) -> int:
        index = 0
        for i in range(self.flow.count()):
            widget = self.flow.itemAt(i).widget()
            if widget is None or widget is self._ghost or not widget.isVisible():
                continue
            r = widget.geometry()
            if pos.y() < r.top():
                return index
            if pos.y() <= r.bottom() and pos.x() < r.center().x():
                return index
            index += 1
        return index

    def _show_ghost(self, pos: QPoint, md: QMimeData) -> None:
        index = self._index_at(pos)
        if self._ghost is not None and index == self._ghost_at:
            return
        self._remove_ghost()
        ghost = QLabel(self)
        ghost.setObjectName("CardGhost")
        if md.hasFormat(MIME_CARD) and _GHOST is not None:
            ghost.setPixmap(_GHOST)
        else:
            name = bytes(md.data(MIME_PARAM)).decode().partition("\n")[0]
            ghost.setText(f"+  {name}")
            ghost.setAlignment(Qt.AlignCenter)
            ghost.setFixedSize(self._card_width(), 64)
        # the place among the visible cards -> the place in the layout
        seen, at = 0, self.flow.count()
        for i in range(self.flow.count()):
            widget = self.flow.itemAt(i).widget()
            if widget is None or not widget.isVisible():
                continue
            if seen == index:
                at = i
                break
            seen += 1
        self.flow.insert_widget(at, ghost)
        ghost.show()
        self._ghost, self._ghost_at = ghost, index

    def _card_width(self) -> int:
        for card in self.cards.values():
            return card.width()
        return CARD_W

    def _remove_ghost(self) -> None:
        ghost, self._ghost, self._ghost_at = self._ghost, None, -1
        if ghost is not None:
            self.flow.removeWidget(ghost)
            ghost.deleteLater()

    @staticmethod
    def _wanted(event) -> bool:
        md = event.mimeData()
        return md.hasFormat(MIME_CARD) or md.hasFormat(MIME_PARAM)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._wanted(event):
            event.acceptProposedAction()
            self._show_ghost(event.position().toPoint(), event.mimeData())

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._wanted(event):
            event.acceptProposedAction()
            self._show_ghost(event.position().toPoint(), event.mimeData())

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._remove_ghost()

    def dropEvent(self, event) -> None:  # noqa: N802
        md = event.mimeData()
        index = self._ghost_at if self._ghost is not None else self._index_at(
            event.position().toPoint())
        self._remove_ghost()
        if md.hasFormat(MIME_CARD):
            event.acceptProposedAction()
            self.moved.emit(bytes(md.data(MIME_CARD)).decode(), index)
        elif md.hasFormat(MIME_PARAM):
            name, _sep, ptype = bytes(md.data(MIME_PARAM)).decode().partition("\n")
            event.acceptProposedAction()
            self.param_dropped.emit(name, ptype, index)


# ----------------------------------------------------------------------
# The parameter list beside the window
# ----------------------------------------------------------------------

class ParamTree(QTreeWidget):
    """The avatar's parameters; a row can be dragged onto a card."""

    def startDrag(self, actions) -> None:  # noqa: N802
        item = self.currentItem()
        if item is None:
            return
        name = item.data(0, Qt.UserRole)
        ptype = item.data(1, Qt.UserRole) or ""
        chip = QLabel(f"+  {name}")
        chip.setObjectName("DragChip")
        chip.ensurePolished()
        chip.adjustSize()
        mime = QMimeData()
        mime.setData(MIME_PARAM, f"{name}\n{ptype}".encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(chip.grab())
        drag.setHotSpot(QPoint(12, 12))
        drag.exec(Qt.CopyAction)


class ParamPicker(QFrame):
    """The avatar's parameters as VRChat lists them. Opening it widens the
    window by its width (the person's own action, like Settings)."""

    picked = Signal(str, str)      # name, type
    closed = Signal()
    refresh = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("PickerPanel")
        lay = vbox(margin=12, spacing=8)
        self.setLayout(lay)
        head = hbox(spacing=6)
        head.addWidget(label("Avatar parameters", "PickerTitle"), 1)
        again = QPushButton("⟳")
        again.setObjectName("Refresh")
        again.setToolTip("Read the list from VRChat again")
        again.clicked.connect(self.refresh.emit)
        head.addWidget(again)
        close = QPushButton("✕")
        close.setObjectName("Refresh")
        close.setToolTip("Close the list")
        close.clicked.connect(self.closed.emit)
        head.addWidget(close)
        lay.addLayout(head)
        self.for_label = label("", "PickerFor", wrap=True)
        lay.addWidget(self.for_label)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter parameters…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda _t: self._apply_filter())
        lay.addWidget(self.filter)
        tree = ParamTree()
        tree.setObjectName("ParamTree")
        tree.setHeaderLabels(["Parameter", "Type", "Value"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setTextElideMode(Qt.ElideMiddle)
        tree.setDragEnabled(True)
        tree.setDragDropMode(QAbstractItemView.DragOnly)
        tree.setSelectionMode(QAbstractItemView.SingleSelection)
        hh = tree.header()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        tree.itemClicked.connect(self._on_click)
        lay.addWidget(tree, 1)
        self.tree = tree
        self.note = hint("")
        lay.addWidget(self.note)
        lay.addWidget(hint("Click one to use it — or drag it onto any card, or onto free "
                           "room among them for a new card."))
        self._items: Dict[str, QTreeWidgetItem] = {}

    def set_for(self, text: str) -> None:
        self.for_label.setText(text)

    def set_rows(self, rows: Optional[Dict[str, Any]], note: str) -> None:
        """rows: {name: (type, value)}; None keeps the list as it is."""
        if rows is not None:
            if set(rows) != set(self._items):
                self.tree.clear()
                self._items = {}
                for name in sorted(rows, key=str.lower):
                    kind, value = rows[name]
                    item = QTreeWidgetItem([name, kind, value_text(value)])
                    item.setToolTip(0, name)
                    item.setData(0, Qt.UserRole, name)
                    item.setData(1, Qt.UserRole, kind)
                    self.tree.addTopLevelItem(item)
                    self._items[name] = item
                self._apply_filter()
            else:
                for name, (kind, value) in rows.items():
                    item = self._items[name]
                    text = value_text(value)
                    if item.text(2) != text:
                        item.setText(2, text)
                    if item.text(1) != kind:
                        item.setText(1, kind)
                        item.setData(1, Qt.UserRole, kind)
        self.note.setText(note)

    def names(self) -> List[str]:
        return list(self._items)

    def _apply_filter(self) -> None:
        needle = self.filter.text().lower().strip()
        for name, item in self._items.items():
            item.setHidden(bool(needle) and needle not in name.lower())

    def _on_click(self, item: QTreeWidgetItem, _column: int) -> None:
        self.picked.emit(item.data(0, Qt.UserRole), item.data(1, Qt.UserRole) or "")
