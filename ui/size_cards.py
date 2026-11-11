"""
The Size parameters card's pieces (ui/window.py builds the card around them).

  * ParamCard — an avatar parameter that grows or shrinks you while it is
    on, on one line of its own: its own pause / play, the parameter's name
    (typed, or Pick… from the list), which way, how fast; under it a line
    saying what it does right now.
  * RandomCard — a random height between two, on 🎲 or when a parameter
    turns on; then select it, go instant or go timed (the saved heights'
    three actions, in their colours).
  * CardBoard — the cards, one under the other, each the full width (Blise:
    "each one of them would be one line so everything has a little bit more
    space, especially the parameter name"): drag one by its ⠿ to sort it; a
    parameter dropped between them makes a new card there. A see-through
    copy shows where it lands.
  * ParamPicker — the avatar's parameters, beside the window (OGP's list):
    filter, click one to use it, or drag it onto a card.

Pure view, like the window: signals out, setters in.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QEvent, QMimeData, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDoubleSpinBox,
    QFrame,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from constants import HOTKEY_SPEED_MIN, MIN_HEIGHT_CM
from height_logic import (KIND_PARAM, KIND_RANDOM, PARAM_GROW, PARAM_SHRINK, SPEED_CM,
                          SPEED_PERCENT, speed_max)

from .theme import colors, text_scale
from .widgets import (HeightSpinBox, Segmented, hbox, hint, label, no_buttons, restyle,
                      toggle_icon, vbox)

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


class NameField(QWidget):
    """A parameter's name: typed (click in and change it), or Pick… from
    the avatar's list beside the window. `committed` when a typed name is
    done (Enter, or clicking elsewhere)."""

    committed = Signal(str)
    pick = Signal()

    def __init__(self, placeholder: str, pick_tip: str) -> None:
        super().__init__()
        lay = hbox(spacing=0)
        self.setLayout(lay)
        self.edit = QLineEdit()
        self.edit.setObjectName("ParamName")
        self.edit.setPlaceholderText(placeholder)
        self.edit.setMinimumWidth(110)
        self.edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.edit.editingFinished.connect(self._done)
        lay.addWidget(self.edit, 1)
        self.pick_btn = QPushButton("Pick…")
        self.pick_btn.setObjectName("PickParam")
        self.pick_btn.setCursor(Qt.PointingHandCursor)
        self.pick_btn.setToolTip(pick_tip)
        self.pick_btn.clicked.connect(self.pick.emit)
        lay.addWidget(self.pick_btn)
        self._shown = ""

    def set_name(self, name: str) -> None:
        self._shown = name
        if not self.edit.hasFocus() or self.edit.text() == name:
            self.edit.setText(name)
            self.edit.setCursorPosition(len(name))     # the end tells two apart
        self.edit.setToolTip(name or self.edit.placeholderText())

    def _done(self) -> None:
        text = self.edit.text().strip()
        if text != self._shown:
            self._shown = text
            self.committed.emit(text)


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
        self.lay = vbox(margin=8, spacing=4)
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
        self.paint_toggle()
        self.on_btn.setToolTip("On — click to pause this card" if on
                               else "Paused — click to switch it back on")
        self.on_btn.setProperty("on", "true" if on else "false")
        restyle(self.on_btn)

    def paint_toggle(self) -> None:
        """Pause bars in cyan while on, a play triangle in amber while paused
        (also again after a text-size or mode change)."""
        on = self.on_btn.isChecked()
        c = colors()
        px = round(14 * max(1.0, text_scale()))
        self.on_btn.setIcon(toggle_icon(on, c["params"] if on else c["amber"], px))
        self.on_btn.setIconSize(QSize(px, px))

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
        self.name = NameField("Parameter name — type it, or Pick…",
                              "Pick it from the avatar's parameters (a list beside the window)")
        self.name.committed.connect(lambda text: self._emit({"param": text, "type": ""}))
        self.name.pick.connect(lambda: self.pick.emit(self.pid))
        self.head.addWidget(self.name, 1)
        self.type_lbl = label("", "CardType")
        self.head.addWidget(self.type_lbl)

        row = self.head                  # one line: everything after the name
        self.dir_seg = Segmented([(PARAM_GROW, "Grow"), (PARAM_SHRINK, "Shrink")])
        self.dir_seg.mark_kinds()
        self.dir_seg.set_tooltips({PARAM_GROW: "Grow while it is on",
                                   PARAM_SHRINK: "Shrink while it is on"})
        self.dir_seg.changed.connect(lambda k: self._emit({"dir": k}))
        row.addWidget(self.dir_seg)
        self.speed_spin = no_buttons(QDoubleSpinBox())
        self.speed_spin.setDecimals(1)
        self.speed_spin.setMinimum(HOTKEY_SPEED_MIN)
        self.speed_spin.setFixedWidth(62)
        self.speed_spin.setToolTip("How fast at full strength: a Bool that is on, a Float at 1")
        self.speed_spin.valueChanged.connect(lambda v: self._emit({"speed": float(v)}))
        row.addWidget(self.speed_spin)
        self.unit_seg = Segmented([(SPEED_CM, "cm/s"), (SPEED_PERCENT, "%/s")])
        self.unit_seg.set_tooltips({
            SPEED_CM: "The same number of centimetres every second",
            SPEED_PERCENT: "The same share of your height every second: feels the same at "
                           "30 cm and at 50 m"})
        self.unit_seg.changed.connect(self._on_unit)
        row.addWidget(self.unit_seg)
        self.finish()

    def set_entry(self, entry: Dict[str, Any]) -> None:
        super().set_entry(entry)
        self._quiet = True
        try:
            self.name.set_name(entry.get("param") or "")
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
        self.head.addWidget(label("🎲  Random", "CardTitle"))
        self.trigger = NameField("Trigger parameter (optional) — type it, or Pick…",
                                 "Pick the parameter that rolls it when it turns on")
        self.trigger.committed.connect(lambda text: self._emit({"param": text, "type": ""}))
        self.trigger.pick.connect(lambda: self.pick.emit(self.pid))
        self.head.addWidget(self.trigger, 1)
        self.roll_btn = QPushButton("🎲  Roll")
        self.roll_btn.setObjectName("Roll")
        self.roll_btn.setCursor(Qt.PointingHandCursor)
        self.roll_btn.setToolTip("Pick a random height now")
        self.roll_btn.clicked.connect(lambda: self.roll.emit(self.pid))
        self.head.addWidget(self.roll_btn)

        rng = hbox(spacing=6)
        rng.addSpacing(4)
        rng.addWidget(label("From", "FieldLabel"))
        self.lo_spin = no_buttons(HeightSpinBox())
        self.hi_spin = no_buttons(HeightSpinBox())
        for spin, key in ((self.lo_spin, "min"), (self.hi_spin, "max")):
            spin.setRange(MIN_HEIGHT_CM, top_cm)
            spin.setFixedWidth(90)
            spin.valueChanged.connect(lambda v, k=key: self._emit({k: float(v)}))
        rng.addWidget(self.lo_spin)
        rng.addWidget(label("to", "FieldLabel"))
        rng.addWidget(self.hi_spin)
        rng.addSpacing(8)
        self.go_seg = Segmented(list(self.ACTIONS))
        self.go_seg.mark_kinds()
        self.go_seg.set_tooltips({
            "select": "Only make it the target: Go instant or Go timed takes you there",
            "instant": "Go there at once",
            "timed": "Go there over the Timed transition's time"})
        self.go_seg.changed.connect(lambda k: self._emit({"go": k}))
        rng.addWidget(self.go_seg)
        rng.addStretch(1)
        self.lay.addLayout(rng)
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
            # empty it to have no trigger: only 🎲 rolls then
            self.trigger.set_name(entry.get("param") or "")
        finally:
            self._quiet = False


# ----------------------------------------------------------------------
# The board
# ----------------------------------------------------------------------

class CardBoard(QWidget):
    """The cards, one per line, each the full width. Sorting a card and
    dropping a parameter between them both show a see-through copy where it
    will land."""

    moved = Signal(str, int)               # card id, its new place
    param_dropped = Signal(str, str, int)  # name, type, place: a new card

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(8)
        self.cards: Dict[str, SizeCard] = {}
        self._ghost: Optional[QLabel] = None
        self._ghost_at = -1

    def set_cards(self, cards: List[SizeCard]) -> None:
        self._remove_ghost()
        while self.column.count():
            item = self.column.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                if isinstance(widget, SizeCard):
                    widget.retired = True
                widget.hide()
                widget.deleteLater()
        self.cards = {}
        for card in cards:
            self.column.addWidget(card)
            self.cards[card.pid] = card
        self.updateGeometry()

    def paint_icons(self) -> None:
        for card in self.cards.values():
            card.paint_toggle()

    # --- where a drop lands ---------------------------------------------------

    def _index_at(self, pos: QPoint) -> int:
        """The place among the visible cards (the ghost and a card being
        carried don't count): above a card's middle, before it."""
        index = 0
        for i in range(self.column.count()):
            widget = self.column.itemAt(i).widget()
            if widget is None or widget is self._ghost or not widget.isVisible():
                continue
            if pos.y() < widget.geometry().center().y():
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
            ghost.setFixedHeight(40)
        # the place among the visible cards -> the place in the layout
        seen, at = 0, self.column.count()
        for i in range(self.column.count()):
            widget = self.column.itemAt(i).widget()
            if widget is None or not widget.isVisible():
                continue
            if seen == index:
                at = i
                break
            seen += 1
        self.column.insertWidget(at, ghost)
        ghost.show()
        self._ghost, self._ghost_at = ghost, index

    def _remove_ghost(self) -> None:
        ghost, self._ghost, self._ghost_at = self._ghost, None, -1
        if ghost is not None:
            self.column.removeWidget(ghost)
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
        close = QPushButton("✕  Close")
        close.setObjectName("PickerClose")
        close.setCursor(Qt.PointingHandCursor)
        close.setToolTip("Put the list away (Pick… on a card opens it again)")
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
