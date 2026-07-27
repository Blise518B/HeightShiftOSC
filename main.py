"""
main.py — HeightShiftOSC controller / entry point.

The controller owns the OSC manager, the config manager, and the Qt
window. It listens to UI signals, drives the OSC manager from the user
gestures, and pushes incoming OSC events back into the UI on the main
thread via QTimer.singleShot — no manual `root.after` plumbing required.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from config_manager import ConfigManager
from constants import (
    APP_NAME,
    BURST_DURATION,
    BURST_INTERVAL,
    CONFIG_FILE_NAME,
    LEGACY_CONFIG_DIR_NAME,
    DEFAULT_HEIGHT_CM,
    DEFAULT_HIDE_CONSOLE,
    DEFAULT_OSC_ROUTER_518,
    DEFAULT_STARTUP_HEIGHT_CM,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    LOG_DATE_FORMAT,
    LOG_FORMAT,
    MAX_HEIGHT_CM,
    MIN_HEIGHT_CM,
)
from osc_manager import VRChatOSCManager
from router518 import Router518KeepAlive
from ui import HeightShiftWindow, apply_global_style
from utils import is_valid_host, round_height_cm
from version import __version__

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Filesystem helpers
# ----------------------------------------------------------------------

def get_app_config_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        config_dir = os.path.join(base, APP_NAME)
        # The app was called HeightShiftOSC before the family-wide naming pass.
        # Adopt the old folder wholesale so profiles and settings survive the
        # rename on any machine this build lands on.
        legacy_dir = os.path.join(base, LEGACY_CONFIG_DIR_NAME)
        if not os.path.isdir(config_dir) and os.path.isdir(legacy_dir):
            try:
                os.rename(legacy_dir, config_dir)
            except OSError:
                pass    # locked or cross-volume: fall through, a fresh dir is made
    elif sys.platform == "darwin":
        config_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_NAME)
    else:
        config_dir = os.path.join(os.path.expanduser("~"), ".config", APP_NAME)
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def get_config_file() -> str:
    return os.path.join(get_app_config_dir(), CONFIG_FILE_NAME)


def get_resource_path(relative_path: str) -> str:
    """Resolve a bundled resource path, working both in dev and PyInstaller."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


# ----------------------------------------------------------------------
# Controller
# ----------------------------------------------------------------------

class HeightShiftController(QObject):
    """Wires the UI, the OSC manager, and the config manager together.

    Inherits QObject so we can declare cross-thread signals — OSC events
    arrive on background threads; the signals marshal them onto the UI
    thread before touching widgets.
    """

    # OSC -> UI bridge signals (these fire on background threads, slots
    # run on the main thread because Qt::AutoConnection upgrades them
    # to QueuedConnection when the sender and receiver live in different
    # threads).
    _osc_height_received = Signal(float)        # raw metres
    _osc_avatar_change = Signal(str)
    _osc_connected = Signal()
    _osc_disconnected = Signal()
    _osc_log = Signal(str)

    def __init__(self, window: HeightShiftWindow):
        super().__init__()
        self.window = window

        self.config_file = get_config_file()
        self.config_manager = ConfigManager(self.config_file)
        cfg = self.config_manager.config

        # State
        self.current_height: int = DEFAULT_HEIGHT_CM
        self.height_loaded: bool = False
        self.last_user_set_height: int = DEFAULT_HEIGHT_CM
        self._height_lock = threading.Lock()

        self.preserve_height_on_avatar: bool = cfg.get(
            "preserve_height_on_avatar_switch", True
        )
        self.hide_console: bool = cfg.get("hide_console", DEFAULT_HIDE_CONSOLE)
        self.osc_router_518: bool = cfg.get("osc_router_518", DEFAULT_OSC_ROUTER_518)
        self.startup_mode: str = cfg.get("startup_mode", "query")
        if self.startup_mode not in ("query", "fixed_height"):
            self.startup_mode = "query"
        self.startup_height: int = int(cfg.get("startup_height", DEFAULT_STARTUP_HEIGHT_CM))

        # Height query retry state. The HTTP endpoint for `/avatar/eyeheight`
        # frequently returns 404 / empty VALUE in the first ~2s after the
        # OSCQuery handshake — VRChat still propagating the avatar's
        # parameter set into its OSCQuery tree. We retry with backoff
        # instead of giving up after one shot.
        self._height_query_attempts = 0
        self._height_query_max_attempts = 8
        self._initial_query_fired = False
        self.slider_min_value: int = int(cfg.get("slider_min_value", MIN_HEIGHT_CM))
        self.slider_max_value: int = int(cfg.get("slider_max_value", MAX_HEIGHT_CM))
        self.osc_ip: str = cfg.get("osc_ip", "127.0.0.1")
        self.profiles = self.config_manager.load_profiles()

        # OSC manager — created here, started after the UI is shown.
        self.osc_manager = VRChatOSCManager(local_listen_port=0)
        self.osc_manager.on_connected = lambda ports: self._osc_connected.emit()
        self.osc_manager.on_disconnected = lambda: self._osc_disconnected.emit()
        self.osc_manager.on_height_received = lambda m: self._osc_height_received.emit(float(m))
        self.osc_manager.on_avatar_change = lambda aid: self._osc_avatar_change.emit(str(aid))
        self.osc_manager.on_log = lambda line: self._osc_log.emit(line)

        # 518 router fallback (see 518Hub docs/STANDARD.md). The OSC
        # receive port binds lazily once VRChat is discovered, so the getter
        # re-reads it each tick — 0 just parks the keep-alive until then.
        self.router518 = Router518KeepAlive(
            lambda: getattr(self.osc_manager, "local_listen_port", 0))

        # Hook UI signals
        self._wire_ui()
        self._wire_osc_bridge()

        # Push initial state into the UI
        self._populate_initial_state()

        # Apply hide_console on boot (Windows only)
        if self.hide_console and sys.platform == "win32":
            QTimer.singleShot(50, lambda: self._toggle_console_visibility(True))

        # Intercept close — controller saves config / stops OSC before exit
        self.window.set_close_handler(self.stop)

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def _wire_ui(self) -> None:
        w = self.window
        w.apply_ip_clicked.connect(self._on_apply_ip)
        w.adjust_clicked.connect(self._on_adjust)
        w.slider_changed.connect(self._on_slider_committed)
        w.slider_dragging.connect(self._on_slider_dragging)
        w.profile_save.connect(self._on_profile_save)
        w.profile_load.connect(self._on_profile_load)
        w.preserve_toggled.connect(self._on_preserve_toggled)
        w.hide_console_toggled.connect(self._on_hide_console_toggled)
        w.osc_router_518_toggled.connect(self._on_osc_router_518_toggled)
        w.startup_mode_changed.connect(self._on_startup_mode_changed)
        w.startup_height_changed.connect(self._on_startup_height_changed)
        w.slider_range_changed.connect(self._on_slider_range_changed)
        w.refresh_height_clicked.connect(self._on_refresh_height)
        w.quit_clicked.connect(self._on_quit)

    def _wire_osc_bridge(self) -> None:
        # AutoConnection → QueuedConnection across threads, so the slots
        # below always run on the main thread.
        self._osc_height_received.connect(self._on_osc_height, Qt.QueuedConnection)
        self._osc_avatar_change.connect(self._on_osc_avatar_change, Qt.QueuedConnection)
        self._osc_connected.connect(self._on_osc_connected, Qt.QueuedConnection)
        self._osc_disconnected.connect(self._on_osc_disconnected, Qt.QueuedConnection)
        self._osc_log.connect(self._on_osc_log, Qt.QueuedConnection)

    def _populate_initial_state(self) -> None:
        w = self.window
        w.set_ip(self.osc_ip)
        w.set_slider_range(self.slider_min_value, self.slider_max_value)
        w.set_slider_value(self.current_height)
        w.set_height_display(None)  # "Not Loaded"
        w.set_preserve(self.preserve_height_on_avatar)
        w.set_hide_console(self.hide_console)
        w.set_osc_router_518(self.osc_router_518)
        w.set_startup_mode(self.startup_mode)
        w.set_startup_height(self.startup_height)
        for i in range(1, 5):
            self._refresh_profile_label(i)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the OSC manager. Startup behaviour is driven by the
        OSC connection callback (`_on_osc_connected`) — querying before
        the OSCQuery handshake completes is pointless."""
        self.osc_manager.start()
        if self.osc_router_518:
            self.router518.start()

        if self.startup_mode == "fixed_height":
            QTimer.singleShot(500, self._apply_fixed_height_startup)
        # else: the `query` startup mode fires its first HTTP query inside
        # `_on_osc_connected`. If VRChat never appears we just stay at
        # "Not Loaded" until the user nudges height with a button.

    def stop(self) -> None:
        self._save_config()
        try:
            self.router518.stop()
        except Exception as e:
            logger.warning(f"Router 518 stop error: {e}")
        try:
            self.osc_manager.stop()
        except Exception as e:
            logger.warning(f"OSC manager stop error: {e}")

    # ------------------------------------------------------------------
    # OSC -> UI slots
    # ------------------------------------------------------------------

    def _on_osc_connected(self) -> None:
        ports = self.osc_manager.ports
        self.window.set_local_port(ports.get("local_listen_port"))
        self.window.set_vrchat_port(ports.get("udp_send_port"))
        self.window.set_connection_status(
            f"Connected to VRChat — "
            f"send to {ports.get('udp_send_port')}, listen on {ports.get('local_listen_port')}",
            connected=True,
        )
        # Kick off the initial height query if we're in "query" mode and
        # the height isn't already loaded (from a previous OSC packet, a
        # manual button press, or a fixed-height startup).
        if (
            self.startup_mode == "query"
            and not self.height_loaded
            and not self._initial_query_fired
        ):
            self._initial_query_fired = True
            self._height_query_attempts = 0
            # Small delay so VRChat has time to populate /avatar/eyeheight
            # in its OSCQuery tree after the handshake completes.
            QTimer.singleShot(800, self._query_height_async)

    def _on_osc_disconnected(self) -> None:
        self.window.set_vrchat_port(None)
        self.window.set_connection_status(
            "Disconnected — waiting for VRChat to reappear…", connected=False
        )

    def _on_osc_height(self, meters: float) -> None:
        height_cm = round_height_cm(meters * 100)
        height_cm = max(MIN_HEIGHT_CM, min(MAX_HEIGHT_CM, height_cm))
        with self._height_lock:
            self.current_height = height_cm
            self.height_loaded = True
            self.last_user_set_height = height_cm
        self.window.set_height_display(height_cm)
        self.window.set_slider_value(height_cm)

    def _on_osc_avatar_change(self, _avatar_id: str) -> None:
        if self.preserve_height_on_avatar:
            logger.info("Avatar change — preserving height with rapid burst.")
            threading.Thread(target=self._rapid_burst_on_avatar_change,
                             daemon=True).start()
        else:
            logger.info("Avatar change — querying new avatar's height.")
            # Reset the latches so the query path actually fires for the
            # new avatar (`_query_height_async` bails when `height_loaded`).
            with self._height_lock:
                self.height_loaded = False
            self.window.set_height_display(None)
            self._height_query_attempts = 0
            QTimer.singleShot(800, self._query_height_async)

    def _on_osc_log(self, line: str) -> None:
        # No log panel yet — logs already go to stdout + file. Reserved for
        # future Diagnostics tab.
        pass

    # ------------------------------------------------------------------
    # UI -> action slots
    # ------------------------------------------------------------------

    def _on_apply_ip(self, ip: str) -> None:
        ip = ip.strip()
        if not is_valid_host(ip):
            logger.warning(f"Invalid IP/host rejected: {ip!r}")
            return
        self.osc_ip = ip
        self.osc_manager.vrc_ip = ip
        if self.osc_manager.osc_client is not None:
            try:
                from pythonosc.udp_client import SimpleUDPClient
                self.osc_manager.osc_client = SimpleUDPClient(
                    ip, self.osc_manager.vrc_osc_port
                )
                logger.info(f"OSC send target updated to {ip}:{self.osc_manager.vrc_osc_port}")
            except Exception as e:
                logger.warning(f"Failed to update OSC client: {e}")
        self._save_config()

    def _on_adjust(self, delta: int) -> None:
        new_height = round_height_cm(self.current_height + delta)
        new_height = max(MIN_HEIGHT_CM, min(MAX_HEIGHT_CM, new_height))
        self._set_height(new_height, send=True)

    def _on_slider_dragging(self, value: int) -> None:
        # Live drag — update display only; don't spam OSC.
        with self._height_lock:
            self.current_height = int(value)
        self.window.set_height_display(int(value))

    def _on_slider_committed(self, value: int) -> None:
        self._set_height(int(value), send=True)

    def _on_slider_range_changed(self, min_val: int, max_val: int) -> None:
        self.slider_min_value = int(min_val)
        self.slider_max_value = int(max_val)
        self._save_config()

    def _on_profile_save(self, profile_num: int) -> None:
        height = self.current_height
        height = max(MIN_HEIGHT_CM, min(MAX_HEIGHT_CM, height))
        self.profiles[f"profile{profile_num}"] = height
        self._save_config()
        self._refresh_profile_label(profile_num)

    def _on_profile_load(self, profile_num: int) -> None:
        key = f"profile{profile_num}"
        if key not in self.profiles:
            logger.debug(f"Profile {profile_num} not set")
            return
        height = int(self.profiles[key])
        height = max(MIN_HEIGHT_CM, min(MAX_HEIGHT_CM, height))
        self._set_height(height, send=True)

    def _on_preserve_toggled(self, checked: bool) -> None:
        self.preserve_height_on_avatar = bool(checked)
        self.config_manager.update_config(
            {"preserve_height_on_avatar_switch": self.preserve_height_on_avatar}
        )

    def _on_hide_console_toggled(self, checked: bool) -> None:
        self.hide_console = bool(checked)
        self.config_manager.update_config({"hide_console": self.hide_console})
        self._toggle_console_visibility(self.hide_console)

    def _on_osc_router_518_toggled(self, checked: bool) -> None:
        self.osc_router_518 = bool(checked)
        if self.osc_router_518:
            self.router518.start()
            logger.info("518 router fallback ON (subscribing at 127.0.0.1:51518)")
        else:
            self.router518.stop()
            logger.info("518 router fallback OFF")
        self.config_manager.update_config({"osc_router_518": self.osc_router_518})

    def _on_startup_mode_changed(self, mode: str) -> None:
        if mode not in ("query", "fixed_height"):
            return
        self.startup_mode = mode
        self.config_manager.update_config({"startup_mode": mode})

    def _on_startup_height_changed(self, value: int) -> None:
        value = max(MIN_HEIGHT_CM, min(MAX_HEIGHT_CM, int(value)))
        self.startup_height = value
        self.config_manager.update_config({"startup_height": value})

    def _on_refresh_height(self) -> None:
        """User clicked the ↻ button — force a fresh height query and
        unconditionally re-arm the resolver loop. Useful for debugging
        when VRChat is being silent."""
        with self._height_lock:
            self.height_loaded = False
        self.window.set_height_display(None)
        self._initial_query_fired = False
        self._height_query_attempts = 0
        # Drop the cached value and re-arm the manager's resolver loop via
        # its public API, so the next query hits the network instead of a
        # stale cache.
        self.osc_manager.force_height_refresh()
        QTimer.singleShot(0, self._query_height_async)

    def _on_quit(self) -> None:
        self.window.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_height(self, height: int, *, send: bool) -> None:
        # Single choke point for committing a height — clamp here so every
        # path (slider commit, profiles, queries, adjust buttons) stays
        # within the app's absolute limits regardless of how the user has
        # configured the slider's visible range.
        height = max(MIN_HEIGHT_CM, min(MAX_HEIGHT_CM, int(height)))
        with self._height_lock:
            self.current_height = height
            self.height_loaded = True
            self.last_user_set_height = height
        self.window.set_height_display(height)
        self.window.set_slider_value(height)
        if send:
            self.osc_manager.send_height(height)

    def _refresh_profile_label(self, profile_num: int) -> None:
        key = f"profile{profile_num}"
        value = self.profiles.get(key)
        self.window.set_profile_value(profile_num, int(value) if value is not None else None)

    def _query_height_async(self) -> None:
        """Fire one HTTP query in a background thread; retry with backoff
        if VRChat hasn't populated `/avatar/eyeheight` yet."""
        if self.height_loaded:
            return  # OSC stream already gave us a height; nothing to do.

        if not self.osc_manager.is_connected:
            # Connection vanished mid-retry — bail; on_connected will
            # re-arm us when it comes back.
            return

        self._height_query_attempts += 1
        attempt = self._height_query_attempts

        def worker() -> None:
            meters = self.osc_manager.query_height_via_http()
            if meters is not None:
                QTimer.singleShot(0, lambda m=meters: self._apply_queried_height(m))
                return
            # No value yet. Retry with exponential-ish backoff capped at 5s,
            # up to _height_query_max_attempts. Avoids hammering VRChat
            # while still recovering when the avatar finishes loading
            # several seconds after the OSCQuery handshake.
            if attempt >= self._height_query_max_attempts:
                logger.info(
                    f"Gave up querying height after {attempt} attempts. "
                    "VRChat will push it via OSC when it changes."
                )
                return
            delay_ms = min(5000, 500 * (2 ** min(attempt - 1, 4)))
            logger.info(
                f"VRChat OSCQuery hasn't populated /avatar/eyeheight yet "
                f"(attempt {attempt}/{self._height_query_max_attempts}); "
                f"retrying in {delay_ms}ms."
            )
            QTimer.singleShot(delay_ms, self._query_height_async)

        threading.Thread(target=worker, daemon=True, name="HeightQuery").start()

    def _apply_queried_height(self, meters: float) -> None:
        height_cm = round_height_cm(meters * 100)
        height_cm = max(MIN_HEIGHT_CM, min(MAX_HEIGHT_CM, height_cm))
        self._set_height(height_cm, send=True)
        logger.info(f"Loaded current height from VRChat: {height_cm}cm")

    def _apply_fixed_height_startup(self) -> None:
        # Wait until OSC is connected before sending; otherwise the
        # height will be lost. Retry every 500ms for up to ~10s.
        if not self.osc_manager.is_connected:
            self._fixed_height_retries = getattr(self, "_fixed_height_retries", 0) + 1
            if self._fixed_height_retries > 20:
                logger.warning("Could not apply fixed height: OSC never connected.")
                return
            QTimer.singleShot(500, self._apply_fixed_height_startup)
            return
        self._set_height(self.startup_height, send=True)
        logger.info(f"Applied fixed startup height: {self.startup_height}cm")

    def _rapid_burst_on_avatar_change(self) -> None:
        """Spam OSC for ~2s after an avatar swap. VRChat discards
        /avatar/eyeheight messages sent immediately after the swap until
        the new avatar's parameter system initialises, so we hammer it
        to catch the first frame where it sticks."""
        with self._height_lock:
            target = self.last_user_set_height
        sends = max(1, int(BURST_DURATION / BURST_INTERVAL))
        logger.info(f"Rapid burst: {sends}× height={target}cm @ {BURST_INTERVAL}s")
        for _ in range(sends):
            self.osc_manager.send_height(target)
            time.sleep(BURST_INTERVAL)
        logger.info("Rapid burst complete.")

    def _save_config(self) -> None:
        with self._height_lock:
            profiles_copy = dict(self.profiles)
        cfg = {
            "osc_ip": self.osc_ip,
            "profiles": profiles_copy,
            "startup_mode": self.startup_mode,
            "startup_height": int(self.startup_height),
            "slider_min_value": int(self.slider_min_value),
            "slider_max_value": int(self.slider_max_value),
            "preserve_height_on_avatar_switch": self.preserve_height_on_avatar,
            "hide_console": self.hide_console,
            "osc_router_518": self.osc_router_518,
        }
        if self.osc_manager.vrc_osc_port:
            cfg["vrchat_discovered_osc_port"] = self.osc_manager.vrc_osc_port
        size = self.window.size()
        cfg["window_geometry"] = f"{size.width()}x{size.height()}"
        self.config_manager.save_config(cfg)

    def _toggle_console_visibility(self, hide: bool) -> None:
        if sys.platform != "win32":
            return
        try:
            kernel32 = ctypes.WinDLL("kernel32")
            user32 = ctypes.WinDLL("user32")
            hwnd = kernel32.GetConsoleWindow()
            if hwnd == 0:
                return
            user32.ShowWindow(hwnd, 0 if hide else 5)  # SW_HIDE=0, SW_SHOW=5
            logger.info(f"Console window {'hidden' if hide else 'shown'}")
        except Exception as e:
            logger.error(f"Could not toggle console visibility: {e}")


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def main() -> int:
    app = QApplication(sys.argv)
    apply_global_style(app)

    icon_path = get_resource_path("OSC_Scale.ico")
    if os.path.exists(icon_path):
        icon = QIcon(icon_path)
        app.setWindowIcon(icon)
    else:
        icon = None

    window = HeightShiftWindow()
    window.setWindowTitle(f"{APP_NAME} - v{__version__}")
    if icon is not None:
        window.setWindowIcon(icon)
    window.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)

    controller = HeightShiftController(window)

    # Try to restore saved geometry
    geom = controller.config_manager.config.get("window_geometry")
    if isinstance(geom, str) and "x" in geom:
        try:
            w, h = geom.lower().split("x", 1)
            window.resize(int(w), int(h))
        except (ValueError, TypeError):
            pass

    window.show()
    controller.start()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
