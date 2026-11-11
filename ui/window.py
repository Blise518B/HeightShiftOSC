"""
The HeightShift main window, in the 518 design system.

Pure view: the controller (controller.py) listens to the signals below and
pushes state in through the public setters; the window never decides what
gets sent to VRChat.

Layout (design-518.md §0):
    header   HeightShift  v2.0 · b14  (connection chip)            [⚙ Settings]
    work     the figure: the height scale (drag NOW / TARGET, click a saved
             height) · NOW in front of TARGET     |  Height: now, nudge now,
                                                     target, load as target,
                                                     save to, Go instant / timed
             Timed transition: over · curve · status | graph
                                                       |  settings side panel
    status   what just happened · (activity chip) · HeightShift v2.0 · made by Blise518B
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QByteArray, QElapsedTimer, QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QActionGroup, QFont, QFontMetrics, QGuiApplication, QKeySequence,
                           QPixmap, QShortcut)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QBoxLayout,
    QGridLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QWidget,
)

from constants import (
    APP_NAME,
    AUTHOR,
    AUTHOR_URL,
    GITHUB_URL,
    MAX_HEIGHT_CM,
    MENU_GUIDE_URL,
    MENU_PREFAB_URL,
    MIN_HEIGHT_CM,
    SAVED_SLOTS,
    UI_UNFOCUSED_MS,
    SEND_RATES,
)
from height_logic import (
    CURVE_LINEAR,
    CURVE_SCALE,
    describe_duration,
    format_height,
    format_height_alt,
    same_height,
)

from . import theme_tokens as T
from .figure import FIT_MIN, SizeComparison, ratio_text
from .graph import GRAPH_HEIGHT, TransitionGraph
from .theme import TEXT_SCALES, colors, resource_path, text_scale
from .update_dialog import UpdateDialog
from .whats_new import WhatsNewDialog
from .widgets import (
    CtrlWheelZoom,
    KeyCaptureButton,
    ModeSwitch,
    Segmented,
    card,
    group,
    hbox,
    hint,
    label,
    no_buttons,
    HeightSpinBox,
    restyle,
    save_icon,
    styled,
    vbox,
)

logger = logging.getLogger(__name__)

DURATION_UNITS = (("s", "sec", 1), ("min", "min", 60), ("h", "hours", 3600))

MENU_HUE = "amber"                      # orange is the updater's (design-518.md)
UPDATE_HUE = "orange"
# Where What's new's "Take me there" leads: (in Settings?, the widget's
# attribute). whats_new.py names them; a test checks every name is here.
PLACES = {
    "slots": (False, "slots_box"),
    "slot_actions": (False, "slots_box"),
    "scale_mode": (False, "mode_switch"),
    "own_height": (False, "reset_btn"),
    "settings_height": (True, "height_group"),
    "updates": (True, "updates_group"),
    "menu_guide": (True, "menu_group"),
}
# A revealed place is lit, goes out for a blink, and is lit again: (ms, lit)
SPOT_BEATS = ((0, True), (450, False), (700, True), (2400, False))
# The VRChat menu, as Settings' mini guide shows it: (depth, icons, name,
# what it does). The icons are the menu's own (assets/menu/, written by
# tools/make_menu_icons.py from docs/unity/icons/).
MENU_GUIDE = (
    (0, ("menu",), "HeightShift", "the submenu in your Action Menu"),
    (1, ("grow",), "Grow", "hold: grow smoothly, at the speed in Grow & shrink while held"),
    (1, ("shrink",), "Shrink", "hold: shrink smoothly, at the same speed"),
    (1, ("play_pause",), "Play / Pause", "Go timed to the target set here; again pauses, "
                                         "again resumes"),
    (1, ("stop",), "Stop", "stops the timed transition where it is"),
    (1, ("saved",), "Saved heights", "a submenu:"),
    (2, ("load1", "load2", "load3", "load4"), "Load 1 – 4",
     "sets your height to saved height 1 – 4 at once"),
    (2, ("save",), "Save current", "a submenu of its own, so a stray tap can't overwrite one:"),
    (3, ("save1", "save2", "save3", "save4"), "Save 1 – 4",
     "stores your current height as saved height 1 – 4"),
)
MENU_ICON_PX = 26                       # at 100 % text
_UNIT_SECONDS = {key: secs for key, _t, secs in DURATION_UNITS}


class HeightShiftWindow(QMainWindow):
    """Main app window. Pure view — the controller pushes state in via the
    public setters and listens to the signals below."""

    # --- user actions ---
    adjust_clicked = Signal(float)            # relative step in cm
    refresh_clicked = Signal()
    reset_clicked = Signal()                  # back to the avatar's own height
    profile_save = Signal(int)
    go_instant_clicked = Signal()             # set the target now, no transition
    play_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    transition_inputs_changed = Signal()
    # --- settings ---
    preserve_toggled = Signal(bool)
    unlock_toggled = Signal(bool)
    send_rate_changed = Signal(int)           # updates a second while a height moves
    router_toggled = Signal(bool)
    hide_console_toggled = Signal(bool)
    startup_mode_changed = Signal(str)        # "query" | "fixed_height"
    startup_height_changed = Signal(float)
    slider_range_changed = Signal(float, float)
    ui_mode_changed = Signal(str)
    text_scale_changed = Signal(float)
    settings_toggled = Signal(bool)
    geometry_changed = Signal()
    hotkeys_toggled = Signal(bool)
    hotkey_captured = Signal(str, int, int)   # "grow" | "shrink", vk, mods
    hotkey_speed_changed = Signal(float, str) # speed, "pct" | "cm"
    hotkeys_vrchat_only_toggled = Signal(bool)
    # --- what a click does ---
    slot_action_changed = Signal(int, str)    # saved height N: "select" | "instant" | "timed"
    scale_mode_changed = Signal(str)          # a click on the scale: the same three
    # --- updates ---
    update_chip_clicked = Signal()            # the header's "update available" chip
    check_updates_clicked = Signal()          # Settings → Check for updates now
    update_install_clicked = Signal()         # the update window's Install now
    update_skipped = Signal(str)              # "don't remind me about <tag>"
    whats_new_clicked = Signal()              # Settings → Updates → What's new

    SETTINGS_WIDTH = 360

    def __init__(self, title_tag: str, version_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} {title_tag}")
        self._title_tag = title_tag
        self._version_text = version_text
        self._close_handler = None
        self._suppress = False
        self._slider_lo, self._slider_hi = float(MIN_HEIGHT_CM), float(MAX_HEIGHT_CM)
        self._height_known = False
        self._ratio: Tuple[str, str] = ("", "")        # what the ratio line says
        self._saved: Dict[int, Optional[float]] = {}   # the saved heights (SAVED_SLOTS)
        self._slot_actions: Dict[int, str] = {}         # what a click on each does
        self.slot_kind_btns: Dict[int, QPushButton] = {}  # its ▾, while Settings are open
        self._slot_menus: Dict[int, QMenu] = {}
        self._pick_ok: Dict[int, Tuple[bool, str]] = {}
        self._target_editable = True
        self._now_cm: Optional[float] = None          # what the comparison shows
        self._target_cm: Optional[float] = None
        self.profile_values: Dict[int, QLabel] = {}
        self.profile_save_btns: Dict[int, QPushButton] = {}
        self.profile_load_btns: Dict[int, QPushButton] = {}
        self.capturing_key = False      # a hotkey button waits for a key press

        # pace(): what a stream changes, drawn at the window's own pace
        self._paced: Dict[str, object] = {}          # key -> the newest update waiting
        self._paced_at: Dict[str, int] = {}          # key -> when it last ran (ms)
        self._pace_clock = QElapsedTimer()
        self._pace_clock.start()
        self._pace_timer = QTimer(self)
        self._pace_timer.setSingleShot(True)
        self._pace_timer.timeout.connect(self._run_paced)

        self._geo_timer = QTimer(self)
        self._geo_timer.setSingleShot(True)
        self._geo_timer.setInterval(600)
        self._geo_timer.timeout.connect(self.geometry_changed.emit)

        self._build()
        self._build_shortcuts()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build(self) -> None:
        body = styled(QWidget(), "Body")
        self.setCentralWidget(body)
        root = vbox(spacing=0)
        body.setLayout(root)

        root.addWidget(self._build_header())

        middle = hbox(spacing=0)
        root.addLayout(middle, 1)

        # The window can't get narrower than its cards (_fit_work_column), so
        # the work column only ever scrolls sideways on a screen too narrow
        # for them, rather than cutting them off.
        self.work_scroll = QScrollArea()
        self.work_scroll.setWidgetResizable(True)
        self.work_scroll.setFrameShape(QFrame.NoFrame)
        self.work = styled(QWidget(), "WorkColumn")
        work_lay = vbox(margin=12, spacing=10)
        self.work.setLayout(work_lay)
        # Top: the figure with its scale, and the Height panel beside it (in
        # a narrow window the figure shrinks first, and only then does the
        # panel go under it, see _arrange_top_row).
        # Below: the timed transition's timing.
        self.top_row = QBoxLayout(QBoxLayout.LeftToRight)
        self.top_row.setSpacing(10)
        self.comparison_card = self._build_comparison()
        self.height_panel = self._build_height_panel()
        self.top_row.addWidget(self.comparison_card, 1)
        self.top_row.addWidget(self.height_panel, 0)
        work_lay.addLayout(self.top_row)
        work_lay.addWidget(self._build_transition_card())
        work_lay.addStretch(1)
        self.work_scroll.setWidget(self.work)
        self.work_scroll.installEventFilter(self)      # its width decides the top row
        middle.addWidget(self.work_scroll, 1)

        self.settings_panel = self._build_settings_panel()
        middle.addWidget(self.settings_panel)

        self._build_status_bar()
        self._fit_work_column()

    def _fit_work_column(self) -> None:
        """The window's narrowest is its narrowest card (the figure at its
        smallest; the Height panel goes under it when the two don't fit
        side by side) plus the settings panel, so nothing is cut off at a
        big text size or in a narrow window (but never wider than the
        screen); a window that has to grow for it stays on its screen.
        Measured after the stylesheet has sized the text (showEvent, and
        once more after a text size change)."""
        self._reserve_widths()
        bar = self.work_scroll.verticalScrollBar().sizeHint().width()
        smallest = self._figure_chrome() + self.figure.stage_size(FIT_MIN)[0]
        need = max(smallest, self.height_panel.minimumSizeHint().width(),
                   self.transition_card.minimumSizeHint().width()) + 24 + bar
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            room = screen.availableGeometry().width() - 16
            if not self.settings_panel.isHidden():
                room -= self.settings_panel.width()
            need = min(need, max(240, room))
        self.work_scroll.setMinimumWidth(need)
        self._arrange_top_row()
        if self.isVisible():
            self.ensure_on_screen()

    def _figure_chrome(self) -> int:
        """The comparison card's width around the figure (margins, border)."""
        return self.comparison_card.minimumSizeHint().width() - self.figure.minimumWidth()

    def _top_row_plan(self, room: int, beside_now: bool) -> Tuple[bool, float]:
        """(beside, the figure's fit) for `room` px of work column: the
        Height panel right of the figure while the two fit, the figure
        shrinking (down to FIT_MIN) to make room; under it only when not
        even the smallest figure fits beside it."""
        chrome = self._figure_chrome()
        panel = self.height_panel.minimumSizeHint().width() + self.top_row.spacing()
        # a little slack before going back beside, so it can't flicker
        fit = self.figure.fit_for(room - panel - chrome - (0 if beside_now else 16))
        if fit is not None:
            return True, fit
        return False, self.figure.fit_for(room - chrome) or FIT_MIN

    def _arrange_top_row(self) -> None:
        bar = self.work_scroll.verticalScrollBar().sizeHint().width()
        # as if the scroll bar were always there, so it coming or going (the
        # figure's height changes the column's) can't flip the row
        room = self.work_scroll.width() - bar - 24
        beside, fit = self._top_row_plan(
            room, self.top_row.direction() == QBoxLayout.LeftToRight)
        self.figure.set_fit(fit)
        want = QBoxLayout.LeftToRight if beside else QBoxLayout.TopToBottom
        if self.top_row.direction() != want:
            self.top_row.setDirection(want)

    # --- pacing (OscGoesPurrr's rule: draw what is seen, as often as useful) ---

    def pace_interval_ms(self) -> Optional[int]:
        """How often a stream may redraw: at once while this window has the
        focus (or was never shown: tests), every UI_UNFOCUSED_MS while
        another window has it — never frozen, it may be watched in a VR
        overlay — and not at all (None) while minimized."""
        if self.isMinimized():
            return None
        if self.isVisible() and not self.isActiveWindow():
            return UI_UNFOCUSED_MS
        return 0

    def pace(self, key: str, update) -> None:
        """Run `update` (a redraw from a stream: a transition tick, VRChat's
        echo) now, or — when it ran less than the pace ago, or the window is
        minimized — later, once, with only the newest one kept per `key`."""
        interval = self.pace_interval_ms()
        last = self._paced_at.get(key)
        elapsed = self._pace_clock.elapsed()
        if interval == 0 or (interval is not None and (last is None or elapsed - last >= interval)):
            self._paced.pop(key, None)
            self._paced_at[key] = elapsed
            update()
            return
        self._paced[key] = update
        if interval is not None and not self._pace_timer.isActive():
            self._pace_timer.start(max(1, interval - (elapsed - (last or 0))))

    def _run_paced(self) -> None:
        if self.pace_interval_ms() is None:
            return                     # minimized: caught up when it comes back
        waiting, self._paced = self._paced, {}
        for key, update in waiting.items():
            self._paced_at[key] = self._pace_clock.elapsed()
            update()

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        if event.type() in (QEvent.WindowStateChange, QEvent.ActivationChange) and self._paced:
            QTimer.singleShot(0, self._run_paced)      # back on screen / in front: catch up

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.work_scroll and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._arrange_top_row)
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._geo_timer.start()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_work_column)

    def _build_header(self) -> QWidget:
        header = styled(QWidget(), "Header")
        lay = hbox(spacing=8)
        lay.setContentsMargins(14, 8, 14, 8)
        header.setLayout(lay)
        title = label(APP_NAME, "AppTitle")
        lay.addWidget(title)
        lay.addWidget(label(self._title_tag, "VersionTag"))
        lay.addSpacing(6)
        self.connection_chip = label("searching for VRChat", "Chip")
        self.connection_chip.setProperty("state", "warn")
        lay.addWidget(self.connection_chip)
        # orange, only while a newer release is out: click for the update window
        self.update_chip = QPushButton("")
        self.update_chip.setObjectName("UpdateChip")
        self.update_chip.setCursor(Qt.PointingHandCursor)
        self.update_chip.setToolTip("A newer HeightShift is out — click to see it")
        self.update_chip.clicked.connect(self.update_chip_clicked.emit)
        self.update_chip.hide()
        lay.addWidget(self.update_chip)
        lay.addStretch(1)
        self.settings_btn = QPushButton("⚙  Settings")
        self.settings_btn.setObjectName("Ghost")
        self.settings_btn.setCheckable(True)
        self.settings_btn.setToolTip("Show or fold away the settings panel")
        self.settings_btn.toggled.connect(self._on_settings_button)
        lay.addWidget(self.settings_btn)
        return header

    def _build_comparison(self) -> QFrame:
        """The height scale with NOW in front of TARGET (ui/figure.py). No
        section bar: it is what the window is about, not one more section.
        The scale only picks the target, like the Height panel's field and
        saved heights: nothing on it sends a height. Go instant or Go timed
        does."""
        frame = QFrame()
        frame.setObjectName("Comparison")
        lay = vbox(spacing=0)
        lay.setContentsMargins(12, 10, 12, 10)
        frame.setLayout(lay)
        # what a click on the scale does: only pick the target, or go there
        # at once or over time — one button, unfolding inside the card
        self.mode_switch = ModeSwitch()
        self.mode_switch.changed.connect(self._on_scale_mode)
        lay.addWidget(self.mode_switch)
        lay.addSpacing(4)
        self.figure = SizeComparison()
        self.figure.target_previewed.connect(self._on_scale_target_preview)
        self.figure.target_committed.connect(self._on_scale_target_commit)
        self.figure.load_requested.connect(self._on_pick_profile)
        self.figure.range_committed.connect(self.slider_range_changed.emit)
        lay.addWidget(self.figure, 0, Qt.AlignCenter)
        return frame

    def _reserve_widths(self) -> None:
        """Room for the longest lines the Height panel shows, in the fonts
        the stylesheet gives them right now: their text changes as heights
        come and go, and must never make the window grow by itself."""
        def widest(lab: QWidget, *samples: str, px: int = 0) -> int:
            font = QFont(lab.font())
            if px:
                font.setPixelSize(px)
            fm = QFontMetrics(font)
            return max(fm.horizontalAdvance(t) for t in samples) + 2

        scale = text_scale()
        # the usual lines; a rarer, longer one wraps onto a second line
        self.hero.setMinimumWidth(max(
            widest(self.hero, "999.999 m", px=round(28 * scale)),
            widest(self.hero_sub, "5,000 cm · read from VRChat"),
            widest(self.target_note, "on the way · 12:00 left", "in 10 min, even growth"),
        ))
        # a saved height never clipped ("6 · 999.9 cm", "6 · 99.999 m")
        slot = self.profile_load_btns[1]
        slot_w = widest(slot, "6 · 999.9 cm", "6 · 99.999 m") + 20
        for btn in self.profile_load_btns.values():
            btn.setMinimumWidth(slot_w)

    @staticmethod
    def _key_row(key_name: str, text: str, tip: str, extra: Optional[QWidget] = None,
                 trailing: Optional[QWidget] = None):
        row = hbox(spacing=6)
        key = QLabel()
        key.setObjectName(key_name)
        key.setFixedSize(10, 10)
        key.setToolTip(tip)
        row.addWidget(key, 0, Qt.AlignVCenter)
        micro = label(text, "Micro")
        micro.setToolTip(tip)
        row.addWidget(micro, 0, Qt.AlignVCenter)
        if extra is not None:
            row.addWidget(extra, 0, Qt.AlignVCenter)
        row.addStretch(1)
        if trailing is not None:
            row.addWidget(trailing, 0, Qt.AlignVCenter)
        return row

    def _build_height_panel(self) -> QFrame:
        """Where you are, and where you go: your height and the nudges that
        send at once; the target — dragged on the scale, typed here, or a
        saved height loaded as the target — and the two ways to get there."""
        frame, lay = card("Height")
        lay.setSpacing(2)

        # --- NOW: what VRChat says, and nudges that are sent at once --------
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setObjectName("Refresh")
        self.refresh_btn.setToolTip("Read the current height from VRChat again")
        self.refresh_btn.clicked.connect(self.refresh_clicked.emit)
        # the avatar's own height (before any scaling), shown and one click
        # away — the same as the Reset key
        self.reset_btn = QPushButton("↺  Own height")
        self.reset_btn.setObjectName("OwnHeight")
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.clicked.connect(self.reset_clicked.emit)
        lay.addLayout(self._key_row("KeyNow", "NOW",
                                    "Bright lines: the avatar's height right now",
                                    extra=self.refresh_btn))
        self.hero = label("—", "HeroValue")
        self.hero.setProperty("known", "false")
        hero_row = hbox(spacing=8)
        hero_row.addWidget(self.hero, 1)
        # top right, beside the height: a real button, as big as the others
        hero_row.addWidget(self.reset_btn, 0, Qt.AlignVCenter)
        lay.addLayout(hero_row)
        self.hero_sub = label("waiting for VRChat", "HeroSub", wrap=True)
        lay.addWidget(self.hero_sub)
        lay.addSpacing(2)
        lay.addWidget(label("NUDGE NOW", "Micro"))
        steps = QGridLayout()
        steps.setHorizontalSpacing(6)
        steps.setVerticalSpacing(6)
        self.step_btns = []
        # +N over -N, smallest step first: each column one size, grow in a
        # red frame above shrink in a blue one
        for i, delta in enumerate((1, 10, 100, -1, -10, -100)):
            sign = "+" if delta > 0 else "−"      # a real minus sign
            btn = QPushButton(f"{sign}{abs(delta)}")
            btn.setObjectName("Step")
            btn.setProperty("sign", "plus" if delta > 0 else "minus")
            tip = f"{'Grow' if delta > 0 else 'Shrink'} by {abs(delta)} cm, now"
            btn.setProperty("defaultTip", tip)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _c=False, d=delta: self.adjust_clicked.emit(float(d)))
            self.step_btns.append(btn)
            steps.addWidget(btn, i // 3, i % 3)
        lay.addLayout(steps)

        # --- TARGET: dragged on the scale, typed, or a saved height --------
        lay.addSpacing(6)
        self.ratio_value = label("", "RatioValue")      # ×29.4 bigger, one baseline
        self.ratio_value.setTextFormat(Qt.RichText)
        lay.addLayout(self._key_row("KeyTarget", "TARGET",
                                    "The shadow: where Go instant or Go timed takes you",
                                    trailing=self.ratio_value))
        self.target_spin = no_buttons(HeightSpinBox())
        self.target_spin.setObjectName("TargetField")
        self.target_spin.setRange(MIN_HEIGHT_CM, MAX_HEIGHT_CM)
        self.target_spin.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.target_spin.setToolTip("Type a height — 170, 1.7 m, 1,7 m, 50 m, 1.2 km — or "
                                    "drag the pointer on the scale.")
        self.target_spin.valueChanged.connect(self._on_transition_inputs)
        lay.addWidget(self.target_spin)
        self.target_note = label("", "TargetNote", wrap=True)
        lay.addWidget(self.target_note)

        lay.addSpacing(4)
        self.slots_box = QFrame()
        self.slots_box.setObjectName("SpotBox")       # What's new can light it up
        box_lay = vbox(spacing=2)
        box_lay.setContentsMargins(3, 3, 3, 3)
        self.slots_box.setLayout(box_lay)
        lay.addWidget(self.slots_box)
        box_lay.addWidget(label("LOAD AS TARGET", "Micro"))
        picks = QGridLayout()
        picks.setHorizontalSpacing(6)
        picks.setVerticalSpacing(6)
        for i in range(1, SAVED_SLOTS + 1):
            pick = QPushButton(f"{i} · empty")
            pick.setObjectName("Slot")
            pick.setCheckable(True)              # checked: it is the target now
            pick.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            pick.setProperty("kind", "select")   # pink: go instant, yellow: go timed
            pick.clicked.connect(lambda _c=False, n=i: self._on_pick_profile(n))
            pick.setContextMenuPolicy(Qt.CustomContextMenu)
            pick.customContextMenuRequested.connect(
                lambda _p, n=i: self._slot_menu(n))
            self.profile_values[i] = pick
            self.profile_load_btns[i] = pick
            # while Settings are open, a ▾ joined to its right edge: what a
            # click on it does (select / go instant / go timed)
            kind = QPushButton("▾")
            kind.setObjectName("SlotKind")
            kind.setProperty("kind", "select")
            kind.setCursor(Qt.PointingHandCursor)
            kind.setToolTip(f"What a click on saved height {i} does")
            kind.setMenu(self._slot_kind_menu(i))
            kind.hide()
            self.slot_kind_btns[i] = kind
            cell = QWidget()
            cell_lay = hbox(spacing=0)
            cell.setLayout(cell_lay)
            cell_lay.addWidget(pick, 1)
            cell_lay.addWidget(kind)
            picks.addWidget(cell, (i - 1) // 3, (i - 1) % 3)     # three across, two rows
        box_lay.addLayout(picks)
        lay.addWidget(label("SAVE CURRENT HEIGHT TO", "Micro"))
        saves = hbox(spacing=6)
        for i in range(1, SAVED_SLOTS + 1):
            save = QPushButton(f" {i}")
            save.setObjectName("SlotSave")
            save.clicked.connect(lambda _c=False, n=i: self.profile_save.emit(n))
            self.profile_save_btns[i] = save
            saves.addWidget(save, 1)
        lay.addLayout(saves)
        self._paint_icons()

        # --- GO: at once, or over the time set below -------------------------
        # One row that never changes height: Go instant | Go timed, and while
        # a transition runs Stop | Pause (or Resume).
        lay.addSpacing(6)
        go = QGridLayout()
        go.setHorizontalSpacing(8)
        go.setVerticalSpacing(6)
        # Each its own colour (Blise, 2026-11-11): Go instant pink, Go timed
        # yellow like the Timed transition card it runs
        self.go_instant_btn = QPushButton("Go instant")
        self.go_instant_btn.setObjectName("GoInstant")
        self.go_instant_btn.clicked.connect(self.go_instant_clicked.emit)
        self.play_btn = QPushButton("▶  Go timed")
        self.play_btn.setObjectName("GoTimed")
        self.play_btn.clicked.connect(self.play_clicked.emit)
        self.pause_btn = QPushButton("‖  Pause")
        self.pause_btn.setObjectName("GoTimed")      # never shown together with Go timed
        self.pause_btn.clicked.connect(self.pause_clicked.emit)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setToolTip("Stop here: the avatar keeps the height it has reached")
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        go.addWidget(self.go_instant_btn, 0, 0)
        go.addWidget(self.stop_btn, 0, 0)
        go.addWidget(self.play_btn, 0, 1)
        go.addWidget(self.pause_btn, 0, 1)
        lay.addLayout(go)
        lay.addStretch(1)
        # Their text changes as heights come and go: _reserve_widths keeps
        # room for the longest they show instead.
        for lab in (self.hero, self.hero_sub, self.target_note, self.ratio_value):
            lab.setMinimumWidth(1)
        return frame

    def _build_transition_card(self) -> QFrame:
        """Go timed's timing: how long, which curve, the graph of it, and
        what it is doing."""
        frame, lay = card("Timed transition")
        frame.setProperty("hue", "timed")      # Go timed's yellow: frame, bar, choices, graph
        self.transition_card = frame

        top = hbox(spacing=12)
        lay.addLayout(top)
        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.addWidget(label("Over", "FieldLabel"), 0, 0)
        self.duration_spin = no_buttons(QSpinBox())
        self.duration_spin.setRange(1, 999)
        self.duration_spin.setFixedWidth(60)
        self.duration_spin.valueChanged.connect(self._on_transition_inputs)
        form.addWidget(self.duration_spin, 0, 1)
        self.unit_seg = Segmented([(k, t) for k, t, _s in DURATION_UNITS])
        self.unit_seg.changed.connect(lambda _k: self._on_transition_inputs())
        form.addWidget(self.unit_seg, 0, 2)
        form.addWidget(label("Curve", "FieldLabel"), 1, 0)
        self.curve_seg = Segmented([(CURVE_LINEAR, "Even speed"), (CURVE_SCALE, "Even growth")])
        self.curve_seg.changed.connect(lambda _k: self._on_transition_inputs())
        self.curve_seg.set_tooltips({
            CURVE_LINEAR: "The same number of centimetres every second.",
            CURVE_SCALE: "The same percentage every second: a big change such as "
                         "1 m → 50 m looks steady instead of rushing at the start.",
        })
        form.addWidget(self.curve_seg, 1, 1, 1, 2)
        self.transition_status = label("", "TransitionStatus", wrap=True)
        self.transition_status.setMinimumWidth(1)        # wraps; its text changes too
        form.addWidget(self.transition_status, 2, 0, 1, 3)
        form.setRowStretch(3, 1)
        inputs = QWidget()
        inputs.setLayout(form)
        inputs.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        top.addWidget(inputs)
        self.graph = TransitionGraph()
        self.graph.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        top.addWidget(self.graph, 1)
        self.set_transition_state("idle", False, "")
        return frame

    def _build_settings_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("SettingsPanel")
        outer = vbox(spacing=0)
        panel.setLayout(outer)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = styled(QWidget(), "SettingsInner")
        lay = vbox(margin=12, spacing=12)
        inner.setLayout(lay)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self.settings_scroll = scroll

        lay.addWidget(label("Settings", "PanelTitle"))

        # --- Height (green) -------------------------------------------
        frame, g = group("Height", "green")
        self.height_group = frame
        self.preserve_cb = QCheckBox("Keep my height when I switch avatars")
        self.preserve_cb.toggled.connect(self.preserve_toggled.emit)
        g.addWidget(self.preserve_cb)
        g.addWidget(hint("After an avatar change, resends the height you had before for "
                          "about two seconds, and once more if VRChat didn't take it."))
        g.addSpacing(4)
        self.unlock_cb = QCheckBox("Unlock upper limit")
        self.unlock_cb.toggled.connect(self.unlock_toggled.emit)
        g.addWidget(self.unlock_cb)
        g.addWidget(hint("Off: nothing above 100 m is ever sent. On: up to 1000 m, and the "
                          "height scale reaches up to it. VRChat or the world can still cap "
                          "the height lower."))
        g.addSpacing(4)
        rate = hbox(spacing=6)
        rate.addWidget(label("Updates per second", "FieldLabel"))
        rate.addStretch(1)
        self.send_rate_seg = Segmented([(str(r), str(r)) for r in SEND_RATES])
        self.send_rate_seg.changed.connect(lambda k: self.send_rate_changed.emit(int(k)))
        rate.addWidget(self.send_rate_seg)
        g.addLayout(rate)
        g.addWidget(hint("How often a timed transition or a held key (hotkey or VRChat menu) "
                          "sends your height: more is smoother. VRChat sets no limit; if your "
                          "own view jitters while you grow, try fewer."))
        g.addSpacing(4)
        g.addWidget(label("Saved heights", "FieldLabel"))
        g.addWidget(hint("While Settings are open, the ▾ on each saved height sets what a "
                         "click on it does: select it as the target, go there at once "
                         "(pink) or start the timed transition (yellow). Right-click works "
                         "too."))
        g.addSpacing(4)
        g.addWidget(label("Scale range", "FieldLabel"))
        rng = hbox(spacing=6)
        self.range_min_spin = no_buttons(QDoubleSpinBox())
        self.range_max_spin = no_buttons(QDoubleSpinBox())
        for spin in (self.range_min_spin, self.range_max_spin):
            spin.setDecimals(0)
            spin.setSuffix(" cm")
            spin.setGroupSeparatorShown(True)
            spin.setRange(MIN_HEIGHT_CM, MAX_HEIGHT_CM)
            spin.setMinimumWidth(60)
            spin.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            spin.valueChanged.connect(self._on_range_spin)
        rng.addWidget(self.range_min_spin, 1)
        rng.addWidget(label("to", "FieldLabel"))
        rng.addWidget(self.range_max_spin, 1)
        g.addLayout(rng)
        g.addWidget(hint("The two ends of the height scale beside the figure — or click "
                          "MIN's or MAX's number on the scale and type. A narrow "
                          "range gives finer control when dragging; "
                          "the buttons always step in exact centimetres."))
        lay.addWidget(frame)

        # --- Grow & shrink while held (pink: the next unused hue) ---------
        # The speed is shared: the hotkeys and the VRChat menu's Grow /
        # Shrink buttons both use it, so it shows even with hotkeys off.
        self.hotkeys_frame, g = group("Grow & shrink while held", "pink")
        speed = hbox(spacing=6)
        speed.addWidget(label("Speed", "FieldLabel"))
        self.hotkey_speed_spin = no_buttons(QDoubleSpinBox())
        self.hotkey_speed_spin.setDecimals(1)
        self.hotkey_speed_spin.setMinimum(0.1)
        self.hotkey_speed_spin.setMinimumWidth(60)
        self.hotkey_speed_spin.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.hotkey_speed_spin.valueChanged.connect(self._on_hotkey_speed_input)
        speed.addWidget(self.hotkey_speed_spin, 1)
        self.hotkey_unit_seg = Segmented([("pct", "% / s"), ("cm", "cm / s")])
        self.hotkey_unit_seg.set_tooltips({
            "pct": "The same share of your height every second: feels the same at 30 cm "
                   "and at 50 m",
            "cm": "The same number of centimetres every second",
        })
        self.hotkey_unit_seg.changed.connect(lambda _k: self._on_hotkey_speed_input())
        speed.addWidget(self.hotkey_unit_seg)
        g.addLayout(speed)
        self.hotkey_speed_hint = hint("")
        g.addWidget(self.hotkey_speed_hint)
        self.hotkeys_box = QWidget()          # off Windows the keys can't be read
        hk = vbox(spacing=4)
        self.hotkeys_box.setLayout(hk)
        hk.addSpacing(4)
        self.hotkeys_cb = QCheckBox("Hotkeys: grow and shrink while a key is held")
        self.hotkeys_cb.toggled.connect(self.hotkeys_toggled.emit)
        hk.addWidget(self.hotkeys_cb)
        hk.addWidget(hint("Works while you're in VRChat. Holding a key stops a running "
                          "transition and stops at the height limit."))
        self.hotkeys_details = QWidget()
        d = vbox(spacing=4)
        self.hotkeys_details.setLayout(d)
        keys = hbox(spacing=6)
        self.grow_key_btn = KeyCaptureButton()
        self.shrink_key_btn = KeyCaptureButton()
        self.reset_key_btn = KeyCaptureButton()
        for which, title, btn in (("grow", "Grow", self.grow_key_btn),
                                  ("shrink", "Shrink", self.shrink_key_btn)):
            btn.setToolTip(f"Click, then press the key that should {which} you while held")
            btn.captured.connect(lambda vk, mods, w=which: self.hotkey_captured.emit(w, vk, mods))
            btn.capturing_changed.connect(self._on_capturing)
            keys.addWidget(label(title, "FieldLabel"))
            keys.addWidget(btn, 1)
        d.addLayout(keys)
        reset = hbox(spacing=6)
        self.reset_key_btn.setToolTip("Click, then press the key that puts you back at the "
                                      "avatar's own height")
        self.reset_key_btn.captured.connect(
            lambda vk, mods: self.hotkey_captured.emit("reset", vk, mods))
        self.reset_key_btn.capturing_changed.connect(self._on_capturing)
        reset.addWidget(label("Reset", "FieldLabel"))
        reset.addWidget(self.reset_key_btn, 1)
        d.addLayout(reset)
        d.addWidget(hint("Reset: one press puts you back at the avatar's own height — the "
                         "one it has before any scaling (VRChat tells it)."))
        d.addWidget(hint("Click a key's button, then press the key you want — with Ctrl, "
                          "Shift or Alt if you like. Esc cancels."))
        d.addSpacing(4)
        self.vrchat_only_cb = QCheckBox("Only while VRChat is in front")
        self.vrchat_only_cb.toggled.connect(self.hotkeys_vrchat_only_toggled.emit)
        d.addWidget(self.vrchat_only_cb)
        d.addWidget(hint("So the same key typed in Discord or a browser changes nothing."))
        hk.addWidget(self.hotkeys_details)
        g.addWidget(self.hotkeys_box)
        lay.addWidget(self.hotkeys_frame)

        # --- Startup (cyan) -------------------------------------------
        frame, g = group("When VRChat connects", "cyan")
        self.startup_seg = Segmented([("query", "Read my height"),
                                       ("fixed_height", "Set a fixed height")])
        self.startup_seg.changed.connect(self._on_startup_mode)
        g.addWidget(self.startup_seg)
        self.fixed_row = QWidget()
        fr = hbox(spacing=6)
        self.fixed_row.setLayout(fr)
        fr.addWidget(label("Fixed height", "FieldLabel"))
        self.fixed_spin = no_buttons(QDoubleSpinBox())
        self.fixed_spin.setDecimals(1)
        self.fixed_spin.setSuffix(" cm")
        self.fixed_spin.setGroupSeparatorShown(True)
        self.fixed_spin.setRange(MIN_HEIGHT_CM, MAX_HEIGHT_CM)
        self.fixed_spin.valueChanged.connect(
            lambda v: None if self._suppress else self.startup_height_changed.emit(float(v)))
        fr.addWidget(self.fixed_spin, 1)
        g.addWidget(self.fixed_row)
        self.startup_hint = hint("")
        g.addWidget(self.startup_hint)
        lay.addWidget(frame)

        # --- Connection (blue) ----------------------------------------
        frame, g = group("Connection", "blue")
        self.ports_label = label("Waiting for VRChat to appear on the network…", "PortsLine",
                                  wrap=True)
        g.addWidget(self.ports_label)
        g.addWidget(hint("Found automatically through OSCQuery — nothing to set up. "
                          "Turn on OSC in VRChat's Action Menu → Options → OSC."))
        g.addSpacing(4)
        self.router_cb = QCheckBox("OSC Router 518 fallback")
        self.router_cb.toggled.connect(self.router_toggled.emit)
        g.addWidget(self.router_cb)
        g.addWidget(hint("Keeps receiving VRChat's updates through the 518 router when "
                          "VRChat stops discovering new OSC apps after a long session."))
        lay.addWidget(frame)

        # --- Appearance (purple) --------------------------------------
        frame, g = group("Appearance", "purple")
        self.mode_seg = Segmented([(k, T.MODE_LABELS[k]) for k in T.MODE_ORDER])
        self.mode_seg.changed.connect(self.ui_mode_changed.emit)
        g.addWidget(self.mode_seg)
        g.addWidget(hint("Neon outlines everything in green; Midnight keeps the "
                          "frames almost invisible."))
        g.addSpacing(4)
        ts = hbox(spacing=6)
        ts.addWidget(label("Text size", "FieldLabel"))
        self.text_smaller = QPushButton("A−")
        self.text_smaller.clicked.connect(lambda: self._step_text_scale(-1))
        self.text_scale_label = label("100 %", "FieldLabel")
        self.text_scale_label.setAlignment(Qt.AlignCenter)
        self.text_scale_label.setMinimumWidth(48)
        self.text_bigger = QPushButton("A+")
        self.text_bigger.clicked.connect(lambda: self._step_text_scale(+1))
        ts.addWidget(self.text_smaller)
        ts.addWidget(self.text_scale_label)
        ts.addWidget(self.text_bigger)
        ts.addStretch(1)
        g.addLayout(ts)
        g.addWidget(hint("Also Ctrl + mouse wheel, Ctrl + plus / minus, Ctrl + 0 to reset."))
        self.hide_console_cb = QCheckBox("Hide the console window")
        self.hide_console_cb.toggled.connect(self.hide_console_toggled.emit)
        self.hide_console_hint = hint("The black window run.bat opens. It comes back "
                                       "by itself if the app crashes.")
        g.addSpacing(4)
        g.addWidget(self.hide_console_cb)
        g.addWidget(self.hide_console_hint)
        lay.addWidget(frame)

        # --- Updates (orange: updaters, design-518.md) ---------------------
        frame, g = group("Updates", UPDATE_HUE)
        self.updates_group = frame
        self.updates_hint = hint("")
        g.addWidget(self.updates_hint)
        row = hbox(spacing=8)
        self.check_updates_btn = QPushButton("Check for updates now")
        self.check_updates_btn.clicked.connect(self.check_updates_clicked.emit)
        row.addWidget(self.check_updates_btn)
        self.whats_new_btn = QPushButton("What's new")
        self.whats_new_btn.setToolTip("What changed in this version and the ones before it")
        self.whats_new_btn.clicked.connect(self.whats_new_clicked.emit)
        row.addWidget(self.whats_new_btn)
        row.addStretch(1)
        g.addLayout(row)
        self.update_result = label("", "PortsLine", wrap=True)
        self.update_result.hide()
        g.addWidget(self.update_result)
        lay.addWidget(frame)
        self.set_updates_info(False)

        # --- VRChat menu: last, a mini guide -----------------------------
        lay.addWidget(self._build_menu_guide())
        self.set_menu_status(False, False)

        lay.addStretch(1)
        panel.setFixedWidth(self.SETTINGS_WIDTH)
        return panel

    def _build_menu_guide(self) -> QFrame:
        """The VRChat menu: nothing to set — it works as soon as the avatar
        has it. Says whether it does, where to get it, and what each of its
        buttons does, with the menu's own icons."""
        frame, g = group("VRChat menu", MENU_HUE)
        self.menu_group = frame
        self.menu_status = label("", "PortsLine", wrap=True)
        g.addWidget(self.menu_status)
        self.menu_links = label("", "MenuLinks")
        self.menu_links.setTextFormat(Qt.RichText)
        self.menu_links.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.menu_links.setOpenExternalLinks(True)
        self.menu_links.setToolTip("The VRCFury prefab from the newest release on GitHub, "
                                   "and the step-by-step guide")
        g.addWidget(self.menu_links)
        g.addWidget(hint("Drag the prefab onto your avatar in Unity (VRCFury needed) and "
                         "upload. The menu only talks to this app: keep HeightShift running "
                         "and OSC on in VRChat."))
        g.addSpacing(6)
        g.addWidget(label("IN THE MENU", "Micro"))
        self._menu_icons = []                 # (QLabel, icon name): sized in _paint_icons
        for depth, icons, name, what in MENU_GUIDE:
            row = hbox(spacing=8)
            row.setContentsMargins(depth * 14, 0, 0, 0)
            pics = hbox(spacing=2)
            for icon in icons:
                pic = QLabel()
                pic.setObjectName("MenuIcon")
                self._menu_icons.append((pic, icon))
                pics.addWidget(pic)
            row.addLayout(pics)
            text = label(f"<b>{name}</b> — {what}", "MenuGuideLine", wrap=True)
            text.setTextFormat(Qt.RichText)
            text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            row.addWidget(text, 1)
            g.addLayout(row)
        self._render_menu_links()
        self._paint_menu_icons()
        return frame

    def _render_menu_links(self) -> None:
        style = f"color:{T.PALETTE[MENU_HUE][0]}; text-decoration:none; font-weight:600"
        self.menu_links.setText(
            f'<a style="{style}" href="{MENU_PREFAB_URL}">Get the VRCFury prefab</a>'
            f'&nbsp;&nbsp;·&nbsp;&nbsp;'
            f'<a style="{style}" href="{MENU_GUIDE_URL}">How to add it</a>')

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        bar.setMinimumHeight(28)                 # grows with the text size (set_text_scale)
        self.status_msg = label("", "StatusMsg")
        self.status_msg.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status_msg.setContentsMargins(10, 0, 0, 0)
        bar.addWidget(self.status_msg, 1)
        self.activity_chip = label("idle", "Chip")
        bar.addPermanentWidget(self.activity_chip)
        self.identity_tag = label("", "IdentityTag")
        self.identity_tag.setTextFormat(Qt.RichText)
        self.identity_tag.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.identity_tag.setOpenExternalLinks(True)
        self.identity_tag.setToolTip(f"{APP_NAME} on GitHub · {AUTHOR}'s GitHub")
        self.identity_tag.setContentsMargins(4, 0, 12, 0)
        bar.addPermanentWidget(self.identity_tag)
        self._render_identity_tag()

    def _render_identity_tag(self) -> None:
        """Only the author is accent and bold (design-518.md); the app's name
        links to its repository, the author to his GitHub profile."""
        c = colors()
        self.identity_tag.setText(
            f'<a href="{GITHUB_URL}" style="color:{c["dim"]}; text-decoration:none">'
            f'{APP_NAME}</a> v{self._version_text} · made by '
            f'<a href="{AUTHOR_URL}" style="color:{c["accent"]}; text-decoration:none; '
            f'font-weight:600">{AUTHOR}</a>')

    def _build_shortcuts(self) -> None:
        for seq, step in (("Ctrl++", 1), ("Ctrl+=", 1), ("Ctrl+-", -1)):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(lambda s=step: self._step_text_scale(s))
        reset = QShortcut(QKeySequence("Ctrl+0"), self)
        reset.activated.connect(lambda: self.text_scale_changed.emit(1.0))
        QApplication.instance().installEventFilter(CtrlWheelZoom(self, self._step_text_scale))

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _on_settings_button(self, checked: bool) -> None:
        if self._suppress:
            return
        self._show_settings(checked, resize=True)
        self.settings_toggled.emit(checked)

    def _show_settings(self, show: bool, resize: bool) -> None:
        # Opening/folding the panel is the person's own action, so the window
        # may grow or shrink by the panel's width for it (ui-style.md).
        was_visible = not self.settings_panel.isHidden()
        self.settings_panel.setVisible(show)
        # the saved heights' ▾ (what a click does) are a setting: shown with them
        for num, kind in self.slot_kind_btns.items():
            kind.setVisible(show)
            slot = self.profile_load_btns[num]
            slot.setProperty("joined", "true" if show else "false")
            restyle(slot)
        self._fit_work_column()
        if resize and self.isVisible() and was_visible != show:
            delta = self.settings_panel.width() if show else -self.settings_panel.width()
            self.resize(max(self.minimumSizeHint().width(), self.width() + delta), self.height())
            self.ensure_on_screen()

    def _step_text_scale(self, direction: int) -> None:
        current = text_scale()
        idx = min(range(len(TEXT_SCALES)), key=lambda i: abs(TEXT_SCALES[i] - current))
        idx = min(len(TEXT_SCALES) - 1, max(0, idx + direction))
        if TEXT_SCALES[idx] != current:
            self.text_scale_changed.emit(TEXT_SCALES[idx])

    def _on_scale_target_preview(self, cm: float) -> None:
        # Picking on the scale: the target field and numbers follow; the
        # setting is saved once, when the mouse is let go. Nothing is sent.
        self._suppress = True
        try:
            self.target_spin.setValue(cm)
        finally:
            self._suppress = False
        self._target_cm = float(self.target_spin.value())
        self._update_comparison()

    def _on_scale_target_commit(self, cm: float) -> None:
        self._on_scale_target_preview(cm)
        self.transition_inputs_changed.emit()
        self._go(self.mode_switch.mode)

    def _go(self, action: str) -> None:
        """After a pick: nothing more ("select"), or Go instant / Go timed —
        the same buttons, so the same checks decide."""
        if action == "instant":
            self.go_instant_clicked.emit()
        elif action == "timed":
            self.play_clicked.emit()

    def _on_scale_mode(self, mode: str) -> None:
        self.figure.set_click_action(mode)
        self.scale_mode_changed.emit(mode)

    SLOT_KINDS = (("select", "Select — load as the target"),
                  ("instant", "Go instant — pink"), ("timed", "Go timed — yellow"))

    def _slot_kind_menu(self, num: int) -> QMenu:
        """What a click on saved height `num` does: its ▾'s dropdown, and
        its right-click menu (the same one)."""
        menu = QMenu(self)
        group = QActionGroup(menu)
        for key, text in self.SLOT_KINDS:
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setData(key)
            act.setChecked(key == "select")
            group.addAction(act)
            act.triggered.connect(lambda _c=False, k=key: self.slot_action_changed.emit(num, k))
        self._slot_menus[num] = menu
        return menu

    def _slot_menu(self, num: int) -> None:
        """Right-click on a saved height: the same menu as its ▾."""
        btn = self.profile_load_btns[num]
        self._slot_menus[num].exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _on_range_spin(self) -> None:
        if self._suppress:
            return
        lo, hi = self.range_min_spin.value(), self.range_max_spin.value()
        if lo < hi:
            self.slider_range_changed.emit(float(lo), float(hi))

    def _on_startup_mode(self, mode_key: str) -> None:
        self._show_startup(mode_key)
        if not self._suppress:
            self.startup_mode_changed.emit(mode_key)

    def _show_startup(self, mode_key: str) -> None:
        fixed = mode_key == "fixed_height"
        self.fixed_row.setVisible(fixed)
        self.startup_hint.setText(
            "Sends this height once, the first time VRChat connects after the app starts."
            if fixed else
            "Only reads the avatar's height. Nothing is sent until you change it.")

    def _on_transition_inputs(self) -> None:
        if not self._suppress:
            self.transition_inputs_changed.emit()

    # ------------------------------------------------------------------
    # Public setters (controller -> view)
    # ------------------------------------------------------------------

    def set_connection(self, connected: bool) -> None:
        self.connection_chip.setText("connected to VRChat" if connected else "searching for VRChat")
        self.connection_chip.setProperty("state", "ok" if connected else "warn")
        restyle(self.connection_chip)

    def set_ports(self, listen_port: Optional[int], vrchat_port: Optional[int]) -> None:
        if vrchat_port:
            self.ports_label.setText(f"Sending to VRChat on port {vrchat_port}, "
                                     f"listening on {listen_port or '…'}.")
        else:
            self.ports_label.setText("Waiting for VRChat to appear on the network…")

    def set_height(self, cm: Optional[float], sub: str) -> None:
        self._height_known = cm is not None
        if cm is None:
            self.hero.setText("not read yet")
            self.hero.setProperty("known", "false")
        else:
            self.hero.setText(format_height(cm))
            self.hero.setProperty("known", "true")
            sub = f"{format_height_alt(cm)} · {sub}" if sub else format_height_alt(cm)
        self.hero_sub.setText(sub)
        restyle(self.hero)
        self._now_cm = cm
        self._update_comparison()

    def _update_comparison(self) -> None:
        """The figure, the target number and the ratio, from what the
        controller last pushed (set_height / set_graph)."""
        now, target = self._now_cm, self._target_cm
        self.figure.set_heights(now, target, animate=self.isVisible())
        for num, btn in self.profile_load_btns.items():
            btn.setChecked(same_height(self._saved.get(num), target))
        big, word = ratio_text(now, target)
        self._ratio = (big, word)
        if big:
            c = colors()
            self.ratio_value.setText(
                f"{big}<span style=\"font-family: 'Segoe UI'; font-weight: 400; "
                f"font-size: {round(12 * text_scale())}px; color: {c['dim']}\">"
                f"&nbsp;&nbsp;{word}</span>")
        else:
            self.ratio_value.setText("")
        self.ratio_value.setVisible(bool(big))           # no empty line while unknown
        self.ratio_value.setProperty("same", "true" if big == "=" else "false")
        # ×10,000,000 in the smaller size, so it fits the room kept for ×999.9
        self.ratio_value.setProperty("long", "true" if len(big) > 6 else "false")
        restyle(self.ratio_value)

    def set_controls_enabled(self, relative: bool, refresh: bool, reason: str) -> None:
        """relative: the ± steps (need VRChat and a known height)."""
        for btn in self.step_btns:
            btn.setEnabled(relative)
            btn.setToolTip(btn.property("defaultTip") if relative else reason)
        self.refresh_btn.setEnabled(refresh)

    def set_slider_range(self, lo: float, hi: float, top_limit: float) -> None:
        self._slider_lo, self._slider_hi = float(lo), float(hi)
        self._suppress = True
        try:
            for spin in (self.range_min_spin, self.range_max_spin):
                spin.setMaximum(top_limit)
            self.range_min_spin.setValue(lo)
            self.range_max_spin.setValue(hi)
        finally:
            self._suppress = False
        self.figure.set_range(self._slider_lo, self._slider_hi, top_limit)

    def set_profile(self, num: int, cm: Optional[float]) -> None:
        lab = self.profile_values.get(num)
        if lab is None:
            return
        lab.setText(f"{num} · {format_height(cm)}" if cm is not None else f"{num} · empty")
        lab.setProperty("empty", "false" if cm is not None else "true")
        restyle(lab)
        self._saved[num] = cm
        self.figure.set_saved(num, cm)
        self._update_comparison()

    def _on_pick_profile(self, num: int) -> None:
        """A saved height becomes the target (nothing is sent: Go instant or
        Go timed does that)."""
        cm = self._saved.get(num)
        ok, _why = self._pick_ok.get(num, (False, ""))
        if cm is None or not ok or not self._target_editable:
            self._update_comparison()          # undo the click's own check mark
            return
        self.target_spin.setValue(cm)          # -> transition_inputs_changed
        self._update_comparison()
        self._go(self._slot_actions.get(num, "select"))

    def _apply_picks(self) -> None:
        locked = ("" if self._target_editable else
                  "The target stays put while the transition runs — Stop it to change it.")
        marks = {}
        for num, btn in self.profile_load_btns.items():
            ok, why = self._pick_ok.get(num, (False, ""))
            usable = ok and self._target_editable
            # Never setEnabled(False): a disabled button gets no right-click,
            # and an empty or locked slot's action must still be settable.
            # It only looks inactive, and a left-click on it does nothing.
            btn.setProperty("usable", "true" if usable else "false")
            btn.setCursor(Qt.PointingHandCursor if usable else Qt.ArrowCursor)
            restyle(btn)
            tip = why if not ok else (locked or why)
            btn.setToolTip((tip + " — " if tip else "") + "right-click: what a click on it does")
            marks[num] = (usable, why if not ok else (locked or why))
        self.figure.set_marks_enabled(marks)

    def set_profile_buttons(self, save_ok: bool, pick_ok: Dict[int, Tuple[bool, str]],
                            save_reason: str) -> None:
        """save_ok: the current height may be stored. pick_ok: which saved
        heights may be loaded as the target, and why not."""
        for num, btn in self.profile_save_btns.items():
            btn.setEnabled(save_ok)
            btn.setToolTip(f"Store your current height as saved height {num}" if save_ok
                           else save_reason)
        self._pick_ok = dict(pick_ok)
        self._apply_picks()

    def set_slot_action(self, num: int, action: str) -> None:
        """What a click on saved height `num` does: its colour, its menu and
        its row in Settings."""
        self._slot_actions[num] = action
        for btn in (self.profile_load_btns.get(num), self.slot_kind_btns.get(num)):
            if btn is not None:
                btn.setProperty("kind", action)
                restyle(btn)
        menu = self._slot_menus.get(num)
        if menu is not None:
            for act in menu.actions():
                act.setChecked(act.data() == action)

    def set_scale_mode(self, mode: str) -> None:
        self.mode_switch.set_mode(mode)
        self.figure.set_click_action(mode)

    def set_own_height(self, cm: Optional[float], key: str, ok: bool) -> None:
        """The reset button: the avatar's own height when VRChat has told it."""
        self.reset_btn.setText(f"↺  Own height · {format_height(cm)}" if cm else "↺  Own height")
        self.reset_btn.setEnabled(ok)
        where = f" — or press {key}" if key else ""
        self.reset_btn.setToolTip(
            ("Back to the avatar's own height, the one it has before any scaling" + where
             if ok else "Waiting for VRChat and the avatar's height"))

    def set_go_instant(self, ok: bool, tip: str) -> None:
        self.go_instant_btn.setEnabled(ok)
        self.go_instant_btn.setToolTip(tip)

    # --- transition -------------------------------------------------

    def transition_inputs(self) -> Tuple[float, int, str, str]:
        """(target_cm, duration_value, unit_key, curve)."""
        return (float(self.target_spin.value()), int(self.duration_spin.value()),
                self.unit_seg.value(), self.curve_seg.value())

    @staticmethod
    def duration_seconds(value: int, unit: str) -> int:
        return int(value) * _UNIT_SECONDS.get(unit, 60)

    def set_transition_inputs(self, target_cm: float, value: int, unit: str, curve: str) -> None:
        self._suppress = True
        try:
            self.target_spin.setValue(target_cm)
            self.duration_spin.setValue(int(value))
            self.unit_seg.set_value(unit)
            self.curve_seg.set_value(curve)
        finally:
            self._suppress = False

    def set_target_limit(self, top_cm: float) -> None:
        for spin in (self.target_spin, self.fixed_spin):
            self._suppress = True
            try:
                spin.setMaximum(top_cm)
            finally:
                self._suppress = False

    def set_transition_state(self, state: str, can_play: bool, status: str,
                             status_state: str = "") -> None:
        """state: idle | playing | paused. Buttons exist only while they have
        something to do."""
        self.play_btn.setVisible(state != "playing")
        self.play_btn.setText("▶  Resume" if state == "paused" else "▶  Go timed")
        self.play_btn.setEnabled(can_play or state == "paused")
        self.pause_btn.setVisible(state == "playing")
        self.stop_btn.setVisible(state in ("playing", "paused"))
        self.go_instant_btn.setVisible(state == "idle")
        editable = state == "idle"
        for w in (self.target_spin, self.duration_spin, self.unit_seg, self.curve_seg):
            w.setEnabled(editable)
        if editable != self._target_editable:
            self._target_editable = editable
            self._apply_picks()
        self.figure.set_target_locked(
            not editable, "The target stays put while the transition runs — Stop it to "
                          "change it." if state == "playing" else
                          "The target stays put while the transition is paused — Stop it "
                          "to change it.")
        self.transition_status.setText(status)
        self.transition_status.setProperty("state", status_state)
        restyle(self.transition_status)

    def set_graph(self, start_cm: Optional[float], end_cm: float, duration_text: str,
                  curve: str, progress: Optional[float]) -> None:
        self.graph.set_plan(start_cm, end_cm, duration_text, curve)
        self.graph.set_progress(progress)
        if end_cm != self._target_cm:
            self._target_cm = end_cm
            self._update_comparison()

    def set_target_note(self, text: str, state: str = "") -> None:
        """The line under TARGET: when it would be reached, or how far the
        running transition has to go."""
        self.target_note.setText(text)
        self.target_note.setProperty("state", state)
        restyle(self.target_note)

    # --- settings ---------------------------------------------------

    def _set_checked(self, box: QCheckBox, checked: bool) -> None:
        box.blockSignals(True)
        box.setChecked(bool(checked))
        box.blockSignals(False)

    def set_preserve(self, checked: bool) -> None:
        self._set_checked(self.preserve_cb, checked)

    def set_unlock(self, checked: bool) -> None:
        self._set_checked(self.unlock_cb, checked)

    def set_send_rate(self, rate: int) -> None:
        self.send_rate_seg.set_value(str(rate))

    def set_router(self, checked: bool) -> None:
        self._set_checked(self.router_cb, checked)

    def set_hide_console(self, checked: bool, available: bool) -> None:
        self._set_checked(self.hide_console_cb, checked)
        # A setting exists only while it has something to do: an exe or
        # pythonw has no console to hide.
        self.hide_console_cb.setVisible(available)
        self.hide_console_hint.setVisible(available)

    def set_hotkeys(self, *, available: bool, enabled: bool, grow: str, shrink: str,
                    speed: float, unit: str, speed_max: float, vrchat_only: bool,
                    reset: str = "") -> None:
        # Off Windows the keys can't be read: only the speed is left (the
        # VRChat menu uses it too).
        self.hotkeys_box.setVisible(available)
        self._set_checked(self.hotkeys_cb, enabled)
        self.hotkeys_details.setVisible(enabled)
        self.grow_key_btn.set_key_text(grow)
        self.shrink_key_btn.set_key_text(shrink)
        self.reset_key_btn.set_key_text(reset)
        self._suppress = True
        try:
            self.hotkey_speed_spin.setMaximum(speed_max)
            self.hotkey_speed_spin.setValue(speed)
            self.hotkey_unit_seg.set_value(unit)
        finally:
            self._suppress = False
        self._set_checked(self.vrchat_only_cb, vrchat_only)
        self._update_hotkey_speed_hint()

    def _on_capturing(self, _on: bool) -> None:
        self.capturing_key = (self.grow_key_btn.capturing or self.shrink_key_btn.capturing
                              or self.reset_key_btn.capturing)

    def _on_hotkey_speed_input(self, *_args) -> None:
        if self._suppress:
            return
        self._update_hotkey_speed_hint()
        self.hotkey_speed_changed.emit(float(self.hotkey_speed_spin.value()),
                                       self.hotkey_unit_seg.value())

    def _update_hotkey_speed_hint(self) -> None:
        speed = float(self.hotkey_speed_spin.value())
        if self.hotkey_unit_seg.value() == "cm":
            secs = 100.0 / speed
            took = f"{secs:.3g} s" if secs < 60 else describe_duration(secs)
            text = f"{speed:g} cm every second: a metre takes {took}."
        else:
            after = format_height(170.0 * (1.0 + speed / 100.0) ** 10)
            text = (f"{speed:g} % of your height every second: {format_height(170.0)} "
                    f"becomes {after} after 10 s, and shrinking takes it back the same way.")
        self.hotkey_speed_hint.setText(text + " The hotkeys and the VRChat menu's Grow and "
                                       "Shrink both use it.")

    def set_menu_status(self, connected: bool, present: Optional[bool]) -> None:
        """Whether the avatar in VRChat has the HeightShift menu: True, False,
        or None while that isn't known yet."""
        if not connected:
            text = "Waiting for VRChat."
        elif present is None:
            text = "Checking whether this avatar has the HeightShift menu…"
        elif present:
            text = "This avatar has the HeightShift menu."
        else:
            text = ("This avatar doesn't have the HeightShift menu. Just added it? VRChat "
                    "keeps an old list of the avatar's parameters until you clear it — "
                    "see How to add it → Troubleshooting.")
        self.menu_status.setText(text)

    # --- updates ------------------------------------------------------------

    def set_updates_info(self, can_install: bool) -> None:
        """Settings → Updates: the version in use, and what an update does."""
        current = self._version_text
        how = ("A newer version installs with one click: the app downloads it, checks it "
               "and restarts itself." if can_install else
               "This copy runs from source: a newer version is offered on the release "
               "page.")
        self.updates_hint.setText(f"You're on v{current}. Checked at every start. {how}")

    def set_update_available(self, tag: Optional[str]) -> None:
        """The header's orange chip: shown while `tag` is newer, else hidden."""
        self.update_chip.setText(f"↑ {tag} available" if tag else "")
        self.update_chip.setVisible(bool(tag))

    def set_update_check_state(self, text: str) -> None:
        """Settings → Updates: what the last check by hand found ("" hides it)."""
        self.update_result.setText(text)
        self.update_result.setVisible(bool(text))
        self.check_updates_btn.setEnabled(text != "Asking GitHub…")

    def show_update_dialog(self, info: dict, can_install: bool) -> UpdateDialog:
        """The update window (one at a time), window-modal, not blocking."""
        news = getattr(self, "whats_new_dialog", None)
        if news is not None and news.isVisible():
            self._update_waiting = (info, can_install)    # after What's new closes
            return None
        old = getattr(self, "update_dialog", None)
        if old is not None and old.isVisible():
            old.raise_()
            old.activateWindow()
            return old
        dlg = UpdateDialog(self, APP_NAME, self._version_text, info, can_install)
        dlg.install_clicked.connect(self.update_install_clicked.emit)
        dlg.skip_changed.connect(self.update_skipped.emit)
        self.update_dialog = dlg
        dlg.open()
        return dlg

    # --- What's new -----------------------------------------------------

    def show_whats_new(self, releases) -> None:
        """The What's new window for `releases` ([(version, items), ...],
        newest first); nothing when there is none or one is open already."""
        releases = [(v, items) for v, items in (releases or []) if items]
        old = getattr(self, "whats_new_dialog", None)
        if not releases or (old is not None and old.isVisible()):
            return
        dlg = WhatsNewDialog(self, releases, self.can_reveal)
        dlg.reveal_requested.connect(self.reveal)
        dlg.finished.connect(self._after_whats_new)
        self.whats_new_dialog = dlg
        dlg.open()

    def _after_whats_new(self, _result) -> None:
        waiting, self._update_waiting = getattr(self, "_update_waiting", None), None
        if waiting:
            QTimer.singleShot(SPOT_BEATS[-1][0] + 400, lambda: self.show_update_dialog(*waiting))

    def can_reveal(self, place: str) -> bool:
        in_settings, attr = PLACES.get(place, (False, ""))
        return bool(attr) and getattr(self, attr, None) is not None

    def reveal(self, place: str) -> bool:
        """Show a place What's new talks about and light it up for a moment:
        Settings open and scrolled to it when it lives there."""
        if not self.can_reveal(place):
            return False
        in_settings, attr = PLACES[place]
        target = getattr(self, attr)
        if attr == "mode_switch":
            target = self.mode_switch.current
        if in_settings:
            if not self.settings_btn.isChecked():
                self.settings_btn.setChecked(True)
            QTimer.singleShot(30, lambda: self.settings_scroll.ensureWidgetVisible(target, 0, 12))
        for at_ms, lit in SPOT_BEATS:
            QTimer.singleShot(at_ms + 30, lambda lit=lit: self._set_spot(target, lit))
        return True

    @staticmethod
    def _set_spot(widget: QWidget, on: bool) -> None:
        widget.setProperty("spot", "true" if on else "false")
        restyle(widget)

    def set_update_progress(self, done: int, total: int) -> None:
        dlg = getattr(self, "update_dialog", None)
        if dlg is not None:
            dlg.set_progress(done, total)

    def set_update_installing(self) -> None:
        dlg = getattr(self, "update_dialog", None)
        if dlg is not None:
            dlg.set_installing()
            dlg.accept()

    def set_update_failed(self, text: str) -> None:
        dlg = getattr(self, "update_dialog", None)
        if dlg is not None:
            dlg.set_failed(text)

    def set_startup(self, mode_key: str, height_cm: float) -> None:
        self._suppress = True
        try:
            self.startup_seg.set_value(mode_key)
            self.fixed_spin.setValue(height_cm)
        finally:
            self._suppress = False
        self._show_startup(mode_key)

    def set_ui_mode(self, mode_key: str) -> None:
        self.mode_seg.set_value(mode_key)
        self._render_identity_tag()
        self.graph.update()
        self.figure.update()
        self._paint_icons()

    def set_text_scale(self, scale: float) -> None:
        self.text_scale_label.setText(f"{round(scale * 100)} %")
        self.text_smaller.setEnabled(scale > TEXT_SCALES[0] + 1e-3)
        self.text_bigger.setEnabled(scale < TEXT_SCALES[-1] - 1e-3)
        self.settings_panel.setFixedWidth(round(self.SETTINGS_WIDTH * max(1.0, scale)))
        self.graph.updateGeometry()
        self.graph.setMinimumHeight(round(GRAPH_HEIGHT * scale))
        self.graph.update()
        self.figure.apply_scale()
        self.statusBar().setMinimumHeight(round(28 * max(1.0, scale)) + 4)
        self._update_comparison()                 # the ratio's word is sized in its text
        self._paint_icons()
        self._fit_work_column()
        QTimer.singleShot(0, self._fit_work_column)    # again, with the new fonts applied

    def _paint_icons(self) -> None:
        """The slots' save arrows, drawn (a font's ⤓ smudges at 13 px)."""
        icon, px = save_icon(colors()["muted"], round(15 * text_scale()))
        for btn in self.profile_save_btns.values():
            btn.setIcon(icon)
            btn.setIconSize(QSize(px, px))
        self._paint_menu_icons()

    def _paint_menu_icons(self) -> None:
        """The VRChat menu's own icons in Settings' mini guide, sharp at any
        DPI and as big as the text."""
        px = round(MENU_ICON_PX * text_scale())
        dpr = self.devicePixelRatioF() or 1.0
        for pic, name in getattr(self, "_menu_icons", ()):
            pix = QPixmap(resource_path(f"assets/menu/{name}.png"))
            if pix.isNull():
                pic.hide()
                continue
            pix = pix.scaled(round(px * dpr), round(px * dpr), Qt.KeepAspectRatio,
                             Qt.SmoothTransformation)
            pix.setDevicePixelRatio(dpr)
            pic.setPixmap(pix)
            pic.setFixedSize(px, px)

    def set_settings_open(self, show: bool) -> None:
        self._suppress = True
        try:
            self.settings_btn.setChecked(show)
        finally:
            self._suppress = False
        self._show_settings(show, resize=False)

    def status(self, text: str) -> None:
        self.status_msg.setText(text)
        self.status_msg.setToolTip(text)

    def set_activity(self, text: str, state: str = "") -> None:
        self.activity_chip.setText(text)
        self.activity_chip.setProperty("state", state)
        restyle(self.activity_chip)

    # ------------------------------------------------------------------
    # Geometry: opens compact, remembers size AND position, stays on screen
    # ------------------------------------------------------------------

    def restore_window(self, saved_b64: str, legacy_size: str, default_w: int,
                       default_h: int) -> None:
        if saved_b64:
            try:
                if self.restoreGeometry(QByteArray.fromBase64(saved_b64.encode("ascii"))):
                    if self._on_screen():
                        return
            except Exception:
                pass
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        w, h = default_w, default_h
        if legacy_size and "x" in legacy_size:
            try:
                lw, lh = (int(x) for x in legacy_size.lower().split("x", 1)[:2])
                w = max(w, lw)
            except ValueError:
                pass
        if avail is not None:
            w = min(w, avail.width() - 40)
            h = min(h, avail.height() - 60)
            self.resize(w, h)
            self.move(avail.center().x() - w // 2, avail.center().y() - h // 2 - 10)
        else:
            self.resize(w, h)

    def geometry_b64(self) -> str:
        return bytes(self.saveGeometry().toBase64()).decode("ascii")

    def _on_screen(self) -> bool:
        frame = self.frameGeometry()
        for screen in QGuiApplication.screens():
            inter = screen.availableGeometry().intersected(frame)
            if inter.width() > 200 and inter.height() > 120:
                return True
        return False

    def ensure_on_screen(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        frame = self.frameGeometry()
        dx = min(0, avail.right() - frame.right()) or max(0, avail.left() - frame.left())
        dy = min(0, avail.bottom() - frame.bottom()) or max(0, avail.top() - frame.top())
        if dx or dy:
            self.move(self.x() + dx, self.y() + dy)

    def bring_to_front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def moveEvent(self, event):  # noqa: N802
        super().moveEvent(event)
        self._geo_timer.start()

    # ------------------------------------------------------------------
    # Close handling
    # ------------------------------------------------------------------

    def set_close_handler(self, cb) -> None:
        self._close_handler = cb

    def closeEvent(self, event):  # noqa: N802
        cb = self._close_handler
        if cb is not None:
            try:
                cb()
            except Exception:
                logger.exception("close handler failed")
        event.accept()
