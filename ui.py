"""
ui.py — PySide6 UI for HeightShiftOSC.

Pure view layer. The controller (`HeightScalerApp` in main.py) wires
signals to slots on the window; the window only paints state.

Theme mirrors OscGoesPurrr: deep indigo background, purple/pink accent,
neon-green success, hot-pink "live" accent. The QSS at the top of this
file is the single source of truth for visual styling.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from constants import (
    APP_NAME,
    COLOR_ALERT,
    COLOR_ALERT_HOVER,
    COLOR_BG,
    COLOR_BUTTON,
    COLOR_BUTTON_HOVER,
    COLOR_INPUT_BG,
    COLOR_INPUT_BORDER,
    COLOR_INPUT_FOCUS,
    COLOR_LIVE,
    COLOR_PRIMARY,
    COLOR_PRIMARY_HOVER,
    COLOR_SUCCESS,
    COLOR_SURFACE,
    COLOR_SURFACE_HOVER,
    COLOR_TEXT,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    DEFAULT_HEIGHT_CM,
    MAX_HEIGHT_CM,
    MIN_HEIGHT_CM,
)

# ============================================================
# Global QSS
# ============================================================

GLOBAL_QSS = f"""
* {{
    color: {COLOR_TEXT};
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog, QWidget#root {{
    background-color: {COLOR_BG};
}}
QFrame#card {{
    background-color: {COLOR_SURFACE};
    border-radius: 12px;
}}
QFrame#cardDark {{
    background-color: {COLOR_BG};
    border-radius: 12px;
}}
QLabel {{
    background: transparent;
}}
QLabel#sectionTitle {{
    color: {COLOR_INPUT_FOCUS};
    font-size: 14px;
    font-weight: bold;
}}
QLabel#heightDisplay {{
    color: {COLOR_TEXT};
    font-size: 40px;
    font-weight: bold;
}}
QLabel#heightDisplayNotLoaded {{
    color: {COLOR_WARNING};
    font-size: 40px;
    font-weight: bold;
}}
QLabel#statusPort {{
    color: {COLOR_SUCCESS};
    font-weight: bold;
}}
QLabel#statusPortPending {{
    color: {COLOR_WARNING};
    font-weight: bold;
}}
QLabel[muted="true"] {{
    color: {COLOR_TEXT_MUTED};
}}
QLabel[connectionState="connected"] {{
    color: {COLOR_SUCCESS};
    font-weight: bold;
}}
QLabel[connectionState="waiting"] {{
    color: {COLOR_WARNING};
}}

QPushButton {{
    background-color: {COLOR_PRIMARY};
    color: {COLOR_TEXT};
    border: none;
    padding: 6px 14px;
    border-radius: 6px;
}}
QPushButton:hover {{
    background-color: {COLOR_PRIMARY_HOVER};
}}
QPushButton:disabled {{
    color: {COLOR_TEXT_MUTED};
    background-color: {COLOR_SURFACE};
}}
QPushButton[role="secondary"] {{
    background-color: {COLOR_BUTTON};
    color: {COLOR_TEXT};
}}
QPushButton[role="secondary"]:hover {{
    background-color: {COLOR_BUTTON_HOVER};
}}
QPushButton[role="success"] {{
    background-color: {COLOR_SUCCESS};
    color: {COLOR_BG};
    font-weight: bold;
}}
QPushButton[role="success"]:hover {{
    background-color: #00E064;
}}
QPushButton[role="danger"] {{
    background-color: {COLOR_ALERT};
    color: {COLOR_TEXT};
    font-weight: bold;
}}
QPushButton[role="danger"]:hover {{
    background-color: {COLOR_ALERT_HOVER};
}}

QLineEdit {{
    background-color: {COLOR_INPUT_BG};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_INPUT_BORDER};
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: {COLOR_PRIMARY};
}}
QLineEdit:focus {{
    border: 1px solid {COLOR_INPUT_FOCUS};
}}
QLineEdit:read-only {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_MUTED};
}}

QComboBox {{
    background-color: {COLOR_INPUT_BG};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_INPUT_BORDER};
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: {COLOR_PRIMARY};
    min-width: 160px;
}}
QComboBox:hover {{
    border-color: {COLOR_INPUT_FOCUS};
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLOR_INPUT_BG};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_INPUT_BORDER};
    selection-background-color: {COLOR_PRIMARY};
    selection-color: {COLOR_TEXT};
    outline: 0;
}}

QCheckBox {{
    background: transparent;
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {COLOR_TEXT_MUTED};
    border-radius: 3px;
    background-color: {COLOR_INPUT_BG};
}}
QCheckBox::indicator:checked {{
    background-color: {COLOR_PRIMARY};
    border: 2px solid {COLOR_TEXT};
}}
QCheckBox::indicator:hover {{
    border-color: {COLOR_INPUT_FOCUS};
}}

QSlider::groove:horizontal {{
    height: 6px;
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {COLOR_PRIMARY},
        stop:1 {COLOR_LIVE}
    );
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: transparent;
}}
QSlider::add-page:horizontal {{
    background: {COLOR_BG};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {COLOR_TEXT};
    width: 14px;
    margin: -6px 0;
    border-radius: 7px;
    border: 2px solid {COLOR_PRIMARY};
}}
QSlider::handle:horizontal:hover {{
    border-color: {COLOR_LIVE};
}}
"""


# ============================================================
# Helpers
# ============================================================

def _vbox(margin: int = 0, spacing: int = 6) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setContentsMargins(margin, margin, margin, margin)
    lay.setSpacing(spacing)
    return lay


def _hbox(margin: int = 0, spacing: int = 6) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(margin, margin, margin, margin)
    lay.setSpacing(spacing)
    return lay


class _Card(QFrame):
    """Rounded section background."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")


# ============================================================
# Main window
# ============================================================

class HeightShiftWindow(QMainWindow):
    """Main app window. Pure view — the controller pushes state in via
    public setters and listens to the signals below."""

    # --- Signals fired in response to user actions ---
    apply_ip_clicked = Signal(str)
    adjust_clicked = Signal(int)          # delta in cm
    slider_changed = Signal(int)          # new value in cm (committed)
    slider_dragging = Signal(int)         # live drag value (no OSC send)
    profile_save = Signal(int)            # profile number (1..4)
    profile_load = Signal(int)
    preserve_toggled = Signal(bool)
    hide_console_toggled = Signal(bool)
    osc_router_518_toggled = Signal(bool)
    startup_mode_changed = Signal(str)    # "query" or "fixed_height"
    startup_height_changed = Signal(int)
    slider_range_changed = Signal(int, int)
    refresh_height_clicked = Signal()
    quit_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("root")
        self.setWindowTitle(APP_NAME)

        # Close handler installed by the controller. Lets the controller
        # save config / stop OSC before the window actually closes without
        # having to monkey-patch closeEvent on the instance.
        self._close_handler: Optional[Callable[[], None]] = None

        # Widget refs we update later
        self.local_port_label: Optional[QLabel] = None
        self.vrchat_port_label: Optional[QLabel] = None
        self.ip_entry: Optional[QLineEdit] = None
        self.height_display: Optional[QLabel] = None
        self.connection_label: Optional[QLabel] = None
        self.height_slider: Optional[QSlider] = None
        self.slider_min_entry: Optional[QLineEdit] = None
        self.slider_max_entry: Optional[QLineEdit] = None
        self.preserve_checkbox: Optional[QCheckBox] = None
        self.hide_console_checkbox: Optional[QCheckBox] = None
        self.osc_router_checkbox: Optional[QCheckBox] = None
        self.startup_combo: Optional[QComboBox] = None
        self.fixed_height_entry: Optional[QLineEdit] = None
        self.profile_value_labels: Dict[int, QLabel] = {}

        # Track committed values so noisy slider updates don't echo OSC
        # for every pixel of drag.
        self._suppress_slider_signal = False
        self._last_committed_slider_value = DEFAULT_HEIGHT_CM

        self._build()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build(self) -> None:
        central = QWidget(self)
        central.setObjectName("root")
        self.setCentralWidget(central)

        root = _vbox(margin=12, spacing=10)
        central.setLayout(root)

        root.addWidget(self._build_osc_card())
        root.addWidget(self._build_height_card())
        root.addWidget(self._build_profiles_card())
        root.addWidget(self._build_settings_card())
        root.addWidget(self._build_startup_card())
        root.addLayout(self._build_quit_row())

    def _build_osc_card(self) -> QFrame:
        card = _Card()
        outer = _vbox(margin=12, spacing=8)
        card.setLayout(outer)

        title = QLabel("OSC Connection")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)

        # Local port + VRChat port on one row
        port_row = _hbox(spacing=10)

        port_row.addWidget(QLabel("Local OSC port:"))
        self.local_port_label = QLabel("…")
        self.local_port_label.setObjectName("statusPortPending")
        self.local_port_label.setMinimumWidth(60)
        port_row.addWidget(self.local_port_label)

        port_row.addSpacing(20)

        port_row.addWidget(QLabel("VRChat OSC port:"))
        self.vrchat_port_label = QLabel("waiting…")
        self.vrchat_port_label.setObjectName("statusPortPending")
        self.vrchat_port_label.setMinimumWidth(60)
        port_row.addWidget(self.vrchat_port_label)

        port_row.addStretch(1)
        outer.addLayout(port_row)

        # IP entry + Apply
        ip_row = _hbox(spacing=8)
        ip_row.addWidget(QLabel("VRChat IP:"))
        self.ip_entry = QLineEdit()
        self.ip_entry.setText("127.0.0.1")
        self.ip_entry.setMaximumWidth(160)
        ip_row.addWidget(self.ip_entry)

        apply_btn = QPushButton("Apply")
        apply_btn.setProperty("role", "secondary")
        apply_btn.clicked.connect(self._on_apply_ip)
        ip_row.addWidget(apply_btn)
        ip_row.addStretch(1)
        outer.addLayout(ip_row)

        # Connection status text
        self.connection_label = QLabel("Waiting for VRChat…")
        self.connection_label.setProperty("muted", "true")
        outer.addWidget(self.connection_label)

        return card

    def _build_height_card(self) -> QFrame:
        card = _Card()
        outer = _vbox(margin=12, spacing=10)
        card.setLayout(outer)

        title = QLabel("Current Height")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)

        # +cm buttons row
        plus_row = _hbox(spacing=8)
        plus_row.addStretch(1)
        for delta in (1, 10, 100):
            btn = QPushButton(f"+{delta} cm")
            btn.setProperty("role", "secondary")
            btn.clicked.connect(lambda _checked=False, d=delta: self.adjust_clicked.emit(d))
            plus_row.addWidget(btn)
        plus_row.addStretch(1)
        outer.addLayout(plus_row)

        # Display + refresh
        display_row = _hbox(spacing=8)
        display_row.addStretch(1)
        self.height_display = QLabel("Not Loaded")
        self.height_display.setObjectName("heightDisplayNotLoaded")
        self.height_display.setAlignment(Qt.AlignCenter)
        display_row.addWidget(self.height_display)
        display_row.addStretch(1)

        refresh_btn = QPushButton("↻")
        refresh_btn.setProperty("role", "secondary")
        refresh_btn.setToolTip("Re-query VRChat for the current eye height")
        refresh_btn.setFixedWidth(36)
        refresh_btn.clicked.connect(self.refresh_height_clicked.emit)
        display_row.addWidget(refresh_btn)
        outer.addLayout(display_row)

        # -cm buttons row
        minus_row = _hbox(spacing=8)
        minus_row.addStretch(1)
        for delta in (1, 10, 100):
            btn = QPushButton(f"-{delta} cm")
            btn.setProperty("role", "secondary")
            btn.clicked.connect(lambda _checked=False, d=-delta: self.adjust_clicked.emit(d))
            minus_row.addWidget(btn)
        minus_row.addStretch(1)
        outer.addLayout(minus_row)

        # Slider + min/max entries
        slider_row = _hbox(spacing=10)
        slider_row.addWidget(QLabel("Min:"))
        self.slider_min_entry = QLineEdit(str(MIN_HEIGHT_CM))
        self.slider_min_entry.setMaximumWidth(60)
        self.slider_min_entry.editingFinished.connect(self._on_slider_range_changed)
        slider_row.addWidget(self.slider_min_entry)

        self.height_slider = QSlider(Qt.Horizontal)
        self.height_slider.setRange(MIN_HEIGHT_CM, MAX_HEIGHT_CM)
        self.height_slider.setValue(DEFAULT_HEIGHT_CM)
        self.height_slider.valueChanged.connect(self._on_slider_value_changed)
        self.height_slider.sliderReleased.connect(self._on_slider_released)
        slider_row.addWidget(self.height_slider, stretch=1)

        slider_row.addWidget(QLabel("Max:"))
        self.slider_max_entry = QLineEdit(str(MAX_HEIGHT_CM))
        self.slider_max_entry.setMaximumWidth(80)
        self.slider_max_entry.editingFinished.connect(self._on_slider_range_changed)
        slider_row.addWidget(self.slider_max_entry)

        outer.addLayout(slider_row)
        return card

    def _build_profiles_card(self) -> QFrame:
        card = _Card()
        outer = _vbox(margin=12, spacing=8)
        card.setLayout(outer)

        title = QLabel("Height Profiles")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)

        for i in range(1, 5):
            row = _hbox(spacing=10)
            label = QLabel(f"Profile {i}:")
            label.setMinimumWidth(80)
            row.addWidget(label)

            value_label = QLabel("—")
            value_label.setProperty("muted", "true")
            value_label.setMinimumWidth(80)
            self.profile_value_labels[i] = value_label
            row.addWidget(value_label)

            row.addStretch(1)

            save_btn = QPushButton("Save")
            save_btn.setProperty("role", "success")
            save_btn.setMaximumWidth(80)
            save_btn.clicked.connect(lambda _c=False, n=i: self.profile_save.emit(n))
            row.addWidget(save_btn)

            load_btn = QPushButton("Load")
            load_btn.setMaximumWidth(80)
            load_btn.clicked.connect(lambda _c=False, n=i: self.profile_load.emit(n))
            row.addWidget(load_btn)

            outer.addLayout(row)
        return card

    def _build_settings_card(self) -> QFrame:
        card = _Card()
        outer = _vbox(margin=12, spacing=8)
        card.setLayout(outer)

        title = QLabel("Settings")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)

        self.preserve_checkbox = QCheckBox("Preserve height on avatar switch")
        self.preserve_checkbox.toggled.connect(self.preserve_toggled.emit)
        outer.addWidget(self.preserve_checkbox)

        self.hide_console_checkbox = QCheckBox("Hide console window")
        self.hide_console_checkbox.toggled.connect(self.hide_console_toggled.emit)
        outer.addWidget(self.hide_console_checkbox)

        self.osc_router_checkbox = QCheckBox("OSC Router 518 fallback (keeps receiving when VRChat discovery dies)")
        self.osc_router_checkbox.toggled.connect(self.osc_router_518_toggled.emit)
        outer.addWidget(self.osc_router_checkbox)

        return card

    def _build_startup_card(self) -> QFrame:
        card = _Card()
        outer = _vbox(margin=12, spacing=8)
        card.setLayout(outer)

        title = QLabel("Startup Mode")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)

        row = _hbox(spacing=10)
        self.startup_combo = QComboBox()
        self.startup_combo.addItem("Query current height", userData="query")
        self.startup_combo.addItem("Load fixed height", userData="fixed_height")
        self.startup_combo.currentIndexChanged.connect(self._on_startup_mode_changed)
        row.addWidget(self.startup_combo)

        self.fixed_height_entry = QLineEdit(str(DEFAULT_HEIGHT_CM))
        self.fixed_height_entry.setMaximumWidth(80)
        self.fixed_height_entry.editingFinished.connect(self._on_startup_height_changed)
        row.addWidget(self.fixed_height_entry)

        row.addStretch(1)
        outer.addLayout(row)
        return card

    def _build_quit_row(self) -> QHBoxLayout:
        row = _hbox(spacing=8)
        row.addStretch(1)
        quit_btn = QPushButton("Quit")
        quit_btn.setProperty("role", "danger")
        quit_btn.setMinimumWidth(100)
        quit_btn.clicked.connect(self.quit_clicked.emit)
        row.addWidget(quit_btn)
        return row

    # ------------------------------------------------------------------
    # Internal slot handlers
    # ------------------------------------------------------------------

    def _on_apply_ip(self) -> None:
        text = self.ip_entry.text().strip() if self.ip_entry else ""
        if text:
            self.apply_ip_clicked.emit(text)

    def _on_slider_value_changed(self, value: int) -> None:
        if self._suppress_slider_signal:
            return
        self.slider_dragging.emit(int(value))

    def _on_slider_released(self) -> None:
        if self._suppress_slider_signal or self.height_slider is None:
            return
        value = self.height_slider.value()
        if value != self._last_committed_slider_value:
            self._last_committed_slider_value = value
            self.slider_changed.emit(int(value))

    def _on_slider_range_changed(self) -> None:
        try:
            min_val = int(float(self.slider_min_entry.text())) if self.slider_min_entry else MIN_HEIGHT_CM
            max_val = int(float(self.slider_max_entry.text())) if self.slider_max_entry else MAX_HEIGHT_CM
        except (ValueError, TypeError):
            return
        # Clamp to the app's absolute limits so the slider can't be widened
        # past the range we'll actually send to VRChat. set_slider_range
        # rewrites the entry text, so the boxes get corrected too.
        min_val = max(MIN_HEIGHT_CM, min(MAX_HEIGHT_CM, min_val))
        max_val = max(MIN_HEIGHT_CM, min(MAX_HEIGHT_CM, max_val))
        if min_val >= max_val:
            return
        self.set_slider_range(min_val, max_val, emit=True)

    def _on_startup_mode_changed(self, index: int) -> None:
        if self.startup_combo is None:
            return
        mode = self.startup_combo.itemData(index)
        if not isinstance(mode, str):
            return
        if self.fixed_height_entry is not None:
            self.fixed_height_entry.setVisible(mode == "fixed_height")
        self.startup_mode_changed.emit(mode)

    def _on_startup_height_changed(self) -> None:
        if self.fixed_height_entry is None:
            return
        try:
            value = int(float(self.fixed_height_entry.text()))
        except (ValueError, TypeError):
            return
        self.startup_height_changed.emit(value)

    # ------------------------------------------------------------------
    # Public setters (controller -> view)
    # ------------------------------------------------------------------

    def set_local_port(self, port: Optional[int]) -> None:
        if self.local_port_label is None:
            return
        if port:
            self.local_port_label.setText(str(port))
            self.local_port_label.setObjectName("statusPort")
        else:
            self.local_port_label.setText("…")
            self.local_port_label.setObjectName("statusPortPending")
        self._restyle(self.local_port_label)

    def set_vrchat_port(self, port: Optional[int]) -> None:
        if self.vrchat_port_label is None:
            return
        if port:
            self.vrchat_port_label.setText(str(port))
            self.vrchat_port_label.setObjectName("statusPort")
        else:
            self.vrchat_port_label.setText("waiting…")
            self.vrchat_port_label.setObjectName("statusPortPending")
        self._restyle(self.vrchat_port_label)

    def set_connection_status(self, text: str, connected: bool) -> None:
        if self.connection_label is None:
            return
        self.connection_label.setText(text)
        self.connection_label.setProperty(
            "connectionState", "connected" if connected else "waiting"
        )
        self._restyle(self.connection_label)

    def set_ip(self, ip: str) -> None:
        if self.ip_entry is not None:
            self.ip_entry.setText(ip)

    def set_height_display(self, height_cm: Optional[int]) -> None:
        if self.height_display is None:
            return
        if height_cm is None:
            self.height_display.setText("Not Loaded")
            self.height_display.setObjectName("heightDisplayNotLoaded")
        else:
            self.height_display.setText(f"{height_cm} cm")
            self.height_display.setObjectName("heightDisplay")
        self._restyle(self.height_display)

    def set_slider_value(self, value: int) -> None:
        if self.height_slider is None:
            return
        self._suppress_slider_signal = True
        try:
            self.height_slider.setValue(int(value))
            self._last_committed_slider_value = int(value)
        finally:
            self._suppress_slider_signal = False

    def set_slider_range(self, minimum: int, maximum: int, *, emit: bool = False) -> None:
        if self.height_slider is None:
            return
        if minimum >= maximum:
            return
        self._suppress_slider_signal = True
        try:
            current = self.height_slider.value()
            self.height_slider.setRange(int(minimum), int(maximum))
            if self.slider_min_entry is not None and self.slider_min_entry.text() != str(minimum):
                self.slider_min_entry.setText(str(minimum))
            if self.slider_max_entry is not None and self.slider_max_entry.text() != str(maximum):
                self.slider_max_entry.setText(str(maximum))
            # Clamp existing position
            clamped = max(minimum, min(maximum, current))
            if clamped != current:
                self.height_slider.setValue(clamped)
                self._last_committed_slider_value = clamped
        finally:
            self._suppress_slider_signal = False
        if emit:
            self.slider_range_changed.emit(int(minimum), int(maximum))

    def set_profile_value(self, profile_num: int, height_cm: Optional[int]) -> None:
        label = self.profile_value_labels.get(profile_num)
        if label is None:
            return
        label.setText(f"{height_cm} cm" if height_cm is not None else "—")

    def set_preserve(self, checked: bool) -> None:
        if self.preserve_checkbox is not None:
            self.preserve_checkbox.blockSignals(True)
            self.preserve_checkbox.setChecked(bool(checked))
            self.preserve_checkbox.blockSignals(False)

    def set_hide_console(self, checked: bool) -> None:
        if self.hide_console_checkbox is not None:
            self.hide_console_checkbox.blockSignals(True)
            self.hide_console_checkbox.setChecked(bool(checked))
            self.hide_console_checkbox.blockSignals(False)

    def set_osc_router_518(self, checked: bool) -> None:
        if self.osc_router_checkbox is not None:
            self.osc_router_checkbox.blockSignals(True)
            self.osc_router_checkbox.setChecked(bool(checked))
            self.osc_router_checkbox.blockSignals(False)

    def set_startup_mode(self, mode: str) -> None:
        if self.startup_combo is None:
            return
        for i in range(self.startup_combo.count()):
            if self.startup_combo.itemData(i) == mode:
                self.startup_combo.blockSignals(True)
                self.startup_combo.setCurrentIndex(i)
                self.startup_combo.blockSignals(False)
                break
        if self.fixed_height_entry is not None:
            self.fixed_height_entry.setVisible(mode == "fixed_height")

    def set_startup_height(self, value: int) -> None:
        if self.fixed_height_entry is not None:
            self.fixed_height_entry.setText(str(int(value)))

    # ------------------------------------------------------------------
    # Close handling
    # ------------------------------------------------------------------

    def set_close_handler(self, cb: Callable[[], None]) -> None:
        """Controller calls this once during wiring."""
        self._close_handler = cb

    def closeEvent(self, event):  # noqa: N802 (Qt API)
        cb = self._close_handler
        if cb is not None:
            try:
                cb()
            except Exception:
                pass
        event.accept()

    # ------------------------------------------------------------------
    # Style helper
    # ------------------------------------------------------------------

    @staticmethod
    def _restyle(widget: QWidget) -> None:
        """Force a QSS re-evaluation after setObjectName / setProperty."""
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


def apply_global_style(app: QApplication) -> None:
    app.setStyleSheet(GLOBAL_QSS)
