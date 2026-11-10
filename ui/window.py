"""
The HeightShift main window, in the 518 design system.

Pure view: the controller (controller.py) listens to the signals below and
pushes state in through the public setters; the window never decides what
gets sent to VRChat.

Layout (design-518.md §0):
    header   HeightShift  v1.1 · b14  (connection chip)            [⚙ Settings]
    work     Height · Slow transition · Profiles      |  settings side panel
    status   what just happened · (activity chip) · HeightShift v1.1 · made by Blise518B
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QByteArray, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QWidget,
)

from constants import APP_NAME, AUTHOR, MAX_HEIGHT_CM, MIN_HEIGHT_CM
from height_logic import (
    CURVE_LINEAR,
    CURVE_SCALE,
    SLIDER_STEPS,
    format_height,
    format_height_alt,
    slider_cm,
    slider_pos,
)

from . import theme_tokens as T
from .graph import GRAPH_HEIGHT, TransitionGraph
from .theme import TEXT_SCALES, colors, text_scale
from .widgets import (
    CtrlWheelZoom,
    Segmented,
    card,
    group,
    hbox,
    hint,
    label,
    no_buttons,
    restyle,
    styled,
    vbox,
)

logger = logging.getLogger(__name__)

DURATION_UNITS = (("s", "sec", 1), ("min", "min", 60), ("h", "hours", 3600))
_UNIT_SECONDS = {key: secs for key, _t, secs in DURATION_UNITS}


class HeightShiftWindow(QMainWindow):
    """Main app window. Pure view — the controller pushes state in via the
    public setters and listens to the signals below."""

    # --- user actions ---
    adjust_clicked = Signal(float)            # relative step in cm
    slider_committed = Signal(float)          # absolute height in cm
    refresh_clicked = Signal()
    profile_save = Signal(int)
    profile_load = Signal(int)
    play_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    transition_inputs_changed = Signal()
    # --- settings ---
    preserve_toggled = Signal(bool)
    unlock_toggled = Signal(bool)
    router_toggled = Signal(bool)
    hide_console_toggled = Signal(bool)
    startup_mode_changed = Signal(str)        # "query" | "fixed_height"
    startup_height_changed = Signal(float)
    slider_range_changed = Signal(float, float)
    ui_mode_changed = Signal(str)
    text_scale_changed = Signal(float)
    settings_toggled = Signal(bool)
    geometry_changed = Signal()

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
        self._hero_sub_text = ""
        self.profile_values: Dict[int, QLabel] = {}
        self.profile_save_btns: Dict[int, QPushButton] = {}
        self.profile_load_btns: Dict[int, QPushButton] = {}

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

        work_scroll = QScrollArea()
        work_scroll.setWidgetResizable(True)
        work_scroll.setFrameShape(QFrame.NoFrame)
        work = styled(QWidget(), "WorkColumn")
        work_lay = vbox(margin=12, spacing=10)
        work.setLayout(work_lay)
        work_lay.addWidget(self._build_height_card())
        work_lay.addWidget(self._build_transition_card())
        work_lay.addWidget(self._build_profiles_card())
        work_lay.addStretch(1)
        work_scroll.setWidget(work)
        middle.addWidget(work_scroll, 1)

        self.settings_panel = self._build_settings_panel()
        middle.addWidget(self.settings_panel)

        self._build_status_bar()

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
        lay.addStretch(1)
        self.settings_btn = QPushButton("⚙  Settings")
        self.settings_btn.setObjectName("Ghost")
        self.settings_btn.setCheckable(True)
        self.settings_btn.setToolTip("Show or fold away the settings panel")
        self.settings_btn.toggled.connect(self._on_settings_button)
        lay.addWidget(self.settings_btn)
        return header

    def _build_height_card(self) -> QFrame:
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setObjectName("Icon")
        self.refresh_btn.setToolTip("Read the current height from VRChat again")
        self.refresh_btn.clicked.connect(self.refresh_clicked.emit)
        frame, lay = card("Height", trailing=self.refresh_btn)

        self.hero = label("—", "HeroValue")
        self.hero.setAlignment(Qt.AlignCenter)
        self.hero.setProperty("known", "false")
        lay.addWidget(self.hero)
        self.hero_sub = label("waiting for VRChat", "HeroSub")
        self.hero_sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.hero_sub)

        steps = hbox(spacing=6)
        steps.addStretch(1)
        self.step_btns = []
        for delta in (-100, -10, -1, 1, 10, 100):
            if delta == 1:
                steps.addSpacing(10)
            sign = "+" if delta > 0 else "−"      # a real minus sign
            btn = QPushButton(f"{sign}{abs(delta)}")
            btn.setObjectName("Step")
            tip = f"{'Grow' if delta > 0 else 'Shrink'} by {abs(delta)} cm"
            btn.setProperty("defaultTip", tip)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _c=False, d=delta: self.adjust_clicked.emit(float(d)))
            self.step_btns.append(btn)
            steps.addWidget(btn)
        steps.addStretch(1)
        lay.addLayout(steps)

        slider_row = hbox(spacing=8)
        self.range_lo = label("", "RangeLabel")
        self.range_hi = label("", "RangeLabel")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, SLIDER_STEPS)
        self.slider.setPageStep(25)
        self.slider.setTracking(False)            # valueChanged on release / click / key
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.valueChanged.connect(self._on_slider_value)
        self.slider.sliderReleased.connect(self._on_slider_released)
        slider_row.addWidget(self.range_lo)
        slider_row.addWidget(self.slider, 1)
        slider_row.addWidget(self.range_hi)
        lay.addLayout(slider_row)
        self._update_range_labels()
        return frame

    def _build_transition_card(self) -> QFrame:
        frame, lay = card("Slow transition")

        self.graph = TransitionGraph()
        lay.addWidget(self.graph)

        row = hbox(spacing=8)
        row.addWidget(label("Target", "FieldLabel"))
        self.target_spin = no_buttons(QDoubleSpinBox())
        self.target_spin.setDecimals(1)
        self.target_spin.setRange(MIN_HEIGHT_CM, MAX_HEIGHT_CM)
        self.target_spin.setSuffix(" cm")
        self.target_spin.setGroupSeparatorShown(True)
        self.target_spin.setMinimumWidth(110)
        self.target_spin.valueChanged.connect(self._on_transition_inputs)
        row.addWidget(self.target_spin)
        row.addSpacing(6)
        row.addWidget(label("over", "FieldLabel"))
        self.duration_spin = no_buttons(QSpinBox())
        self.duration_spin.setRange(1, 999)
        self.duration_spin.setMinimumWidth(60)
        self.duration_spin.valueChanged.connect(self._on_transition_inputs)
        row.addWidget(self.duration_spin)
        self.unit_seg = Segmented([(k, t) for k, t, _s in DURATION_UNITS])
        self.unit_seg.changed.connect(lambda _k: self._on_transition_inputs())
        row.addWidget(self.unit_seg)
        row.addStretch(1)
        lay.addLayout(row)

        curve_row = hbox(spacing=8)
        curve_row.addWidget(label("Curve", "FieldLabel"))
        self.curve_seg = Segmented([(CURVE_LINEAR, "Even speed"), (CURVE_SCALE, "Even growth")])
        self.curve_seg.changed.connect(lambda _k: self._on_transition_inputs())
        self.curve_seg.set_tooltips({
            CURVE_LINEAR: "The same number of centimetres every second.",
            CURVE_SCALE: "The same percentage every second: a big change such as "
                         "1 m → 50 m looks steady instead of rushing at the start.",
        })
        curve_row.addWidget(self.curve_seg)
        self.curve_hint = label("", "Hint")
        curve_row.addWidget(self.curve_hint, 1)
        lay.addLayout(curve_row)

        buttons = hbox(spacing=8)
        self.play_btn = QPushButton("▶  Play")
        self.play_btn.setObjectName("Primary")
        self.play_btn.clicked.connect(self.play_clicked.emit)
        self.pause_btn = QPushButton("‖  Pause")
        self.pause_btn.clicked.connect(self.pause_clicked.emit)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setToolTip("Stop here: the avatar keeps the height it has reached")
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        buttons.addWidget(self.play_btn)
        buttons.addWidget(self.pause_btn)
        buttons.addWidget(self.stop_btn)
        self.transition_status = label("", "TransitionStatus", wrap=True)
        self.transition_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        buttons.addSpacing(6)
        buttons.addWidget(self.transition_status, 1)
        lay.addLayout(buttons)
        self.set_transition_state("idle", False, "")
        return frame

    def _build_profiles_card(self) -> QFrame:
        frame, lay = card("Profiles")
        lay.setSpacing(4)
        for i in range(1, 5):
            row = hbox(spacing=8)
            name = label(f"Profile {i}", "ProfileName")
            name.setMinimumWidth(70)
            row.addWidget(name)
            value = label("empty", "ProfileValue")
            value.setProperty("empty", "true")
            self.profile_values[i] = value
            row.addWidget(value, 1)
            save = QPushButton("Save current")
            save.setObjectName("Small")
            save.clicked.connect(lambda _c=False, n=i: self.profile_save.emit(n))
            load = QPushButton("Load")
            load.setObjectName("Small")
            load.clicked.connect(lambda _c=False, n=i: self.profile_load.emit(n))
            self.profile_save_btns[i] = save
            self.profile_load_btns[i] = load
            row.addWidget(save)
            row.addWidget(load)
            lay.addLayout(row)
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

        lay.addWidget(label("Settings", "PanelTitle"))

        # --- Height (green) -------------------------------------------
        frame, g = group("Height", "green")
        self.preserve_cb = QCheckBox("Keep my height when I switch avatars")
        self.preserve_cb.toggled.connect(self.preserve_toggled.emit)
        g.addWidget(self.preserve_cb)
        g.addWidget(hint("After an avatar change, resends the height you had before for "
                          "about two seconds, and once more if VRChat didn't take it."))
        g.addSpacing(4)
        self.unlock_cb = QCheckBox("Unlock upper limit")
        self.unlock_cb.toggled.connect(self.unlock_toggled.emit)
        g.addWidget(self.unlock_cb)
        g.addWidget(hint("Off: nothing above 100 m is ever sent. On: up to 100 km. "
                          "VRChat or the world can still cap the height lower."))
        g.addSpacing(4)
        g.addWidget(label("Slider range", "FieldLabel"))
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
        g.addWidget(hint("The slider's two ends. A narrow range gives finer control; "
                          "the buttons always step in exact centimetres."))
        lay.addWidget(frame)

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

        lay.addStretch(1)
        panel.setFixedWidth(self.SETTINGS_WIDTH)
        return panel

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        bar.setMinimumHeight(28)
        self.status_msg = label("", "StatusMsg")
        self.status_msg.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status_msg.setContentsMargins(10, 0, 0, 0)
        bar.addWidget(self.status_msg, 1)
        self.activity_chip = label("idle", "Chip")
        bar.addPermanentWidget(self.activity_chip)
        self.identity_tag = label("", "IdentityTag")
        self.identity_tag.setTextFormat(Qt.RichText)
        self.identity_tag.setContentsMargins(4, 0, 12, 0)
        bar.addPermanentWidget(self.identity_tag)
        self._render_identity_tag()

    def _render_identity_tag(self) -> None:
        accent = colors()["accent"]
        self.identity_tag.setText(
            f"{APP_NAME} v{self._version_text} · made by "
            f"<span style='color:{accent}; font-weight:600'>{AUTHOR}</span>")

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

    def _on_slider_moved(self, pos: int) -> None:
        # Live drag: preview only, nothing is sent until release.
        preview = slider_cm(pos, self._slider_lo, self._slider_hi)
        self.hero_sub.setText(f"release to set {format_height(preview)}")

    def _on_slider_value(self, pos: int) -> None:
        # With tracking off this fires on release, on a click in the groove
        # and on arrow keys — every one of them is a deliberate set.
        if self._suppress or self.slider.isSliderDown():
            return
        self.slider_committed.emit(slider_cm(pos, self._slider_lo, self._slider_hi))

    def _on_slider_released(self) -> None:
        # Released at the same position: valueChanged doesn't fire, so put the
        # sub line back (the controller refreshes it on every real change).
        QTimer.singleShot(0, lambda: self.hero_sub.setText(self._hero_sub_text))

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

    def _update_curve_hint(self) -> None:
        self.curve_hint.setText("same cm every second" if self.curve_seg.value() == CURVE_LINEAR
                                else "same % every second")

    def _on_transition_inputs(self) -> None:
        self._update_curve_hint()
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
        self._hero_sub_text = sub
        if not self.slider.isSliderDown():
            self.hero_sub.setText(sub)
        restyle(self.hero)
        if cm is not None:
            self.set_slider(cm)

    def set_controls_enabled(self, relative: bool, absolute: bool, refresh: bool,
                             reason: str) -> None:
        """relative: ± steps (need a known height). absolute: slider / profile
        load (need VRChat connected)."""
        for btn in self.step_btns:
            btn.setEnabled(relative)
            btn.setToolTip(btn.property("defaultTip") if relative else reason)
        self.slider.setEnabled(absolute)
        self.slider.setToolTip("" if absolute else reason)
        self.refresh_btn.setEnabled(refresh)

    def set_slider(self, cm: float) -> None:
        if self.slider.isSliderDown():
            return   # never yank the handle out from under the mouse
        self._suppress = True
        try:
            self.slider.setValue(slider_pos(cm, self._slider_lo, self._slider_hi))
        finally:
            self._suppress = False

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
        self._update_range_labels()

    def _update_range_labels(self) -> None:
        self.range_lo.setText(format_height(self._slider_lo))
        self.range_hi.setText(format_height(self._slider_hi))

    def set_profile(self, num: int, cm: Optional[float]) -> None:
        lab = self.profile_values.get(num)
        if lab is None:
            return
        lab.setText(format_height(cm) if cm is not None else "empty")
        lab.setProperty("empty", "false" if cm is not None else "true")
        restyle(lab)

    def set_profile_buttons(self, save_ok: bool, load_ok: Dict[int, Tuple[bool, str]],
                            save_reason: str) -> None:
        for num, btn in self.profile_save_btns.items():
            btn.setEnabled(save_ok)
            btn.setToolTip("" if save_ok else save_reason)
        for num, btn in self.profile_load_btns.items():
            ok, why = load_ok.get(num, (False, ""))
            btn.setEnabled(ok)
            btn.setToolTip(why)

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
        self._update_curve_hint()

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
        self.play_btn.setText("▶  Resume" if state == "paused" else "▶  Play")
        self.play_btn.setEnabled(can_play or state == "paused")
        self.pause_btn.setVisible(state == "playing")
        self.stop_btn.setVisible(state in ("playing", "paused"))
        editable = state == "idle"
        for w in (self.target_spin, self.duration_spin, self.unit_seg, self.curve_seg):
            w.setEnabled(editable)
        self.transition_status.setText(status)
        self.transition_status.setProperty("state", status_state)
        restyle(self.transition_status)

    def set_graph(self, start_cm: Optional[float], end_cm: float, duration_text: str,
                  curve: str, progress: Optional[float]) -> None:
        self.graph.set_plan(start_cm, end_cm, duration_text, curve)
        self.graph.set_progress(progress)

    # --- settings ---------------------------------------------------

    def _set_checked(self, box: QCheckBox, checked: bool) -> None:
        box.blockSignals(True)
        box.setChecked(bool(checked))
        box.blockSignals(False)

    def set_preserve(self, checked: bool) -> None:
        self._set_checked(self.preserve_cb, checked)

    def set_unlock(self, checked: bool) -> None:
        self._set_checked(self.unlock_cb, checked)

    def set_router(self, checked: bool) -> None:
        self._set_checked(self.router_cb, checked)

    def set_hide_console(self, checked: bool, available: bool) -> None:
        self._set_checked(self.hide_console_cb, checked)
        # A setting exists only while it has something to do: an exe or
        # pythonw has no console to hide.
        self.hide_console_cb.setVisible(available)
        self.hide_console_hint.setVisible(available)

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

    def set_text_scale(self, scale: float) -> None:
        self.text_scale_label.setText(f"{round(scale * 100)} %")
        self.text_smaller.setEnabled(scale > TEXT_SCALES[0] + 1e-3)
        self.text_bigger.setEnabled(scale < TEXT_SCALES[-1] - 1e-3)
        self.settings_panel.setFixedWidth(round(self.SETTINGS_WIDTH * max(1.0, scale)))
        self.graph.updateGeometry()
        self.graph.setMinimumHeight(round(GRAPH_HEIGHT * scale))
        self.graph.update()

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

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._geo_timer.start()

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
