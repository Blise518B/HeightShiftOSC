"""
controller.py — HeightShift's controller: decides what is sent to VRChat.

Owns the OSC manager (osc/), the config and the window (ui/), and keeps the
avatar's height as far as it is known. Two rules hold the whole app together:

  * WRITE: every height that leaves the app goes through `_write()`, which
    refuses anything `height_logic.check_write()` rejects (never clamps it
    into something else) and only sends while VRChat is connected.
  * READ: every height VRChat reports goes through `_on_reported()`. It is
    never clamped, rounded or sent back — on startup the app only reads.
    Relative steps (±1 cm …), profile saves and transitions all need that
    read height first, so nothing is ever computed from a made-up default.

The rules themselves (limits, which report to trust, the transition clock,
which menu reports are presses) live in height_logic.py, without Qt, and are
tested there.

The in-VRChat menu (docs/VRCHAT_MENU.md) is one more way in, never another
way out: its Grow / Shrink are held like the hotkeys, its Play / Stop / Load
/ Save do what the window's buttons do, through the same paths.

Updates (updater.py, VRCParameterRelay's): main.py asks GitHub once at every
start; a newer release lights the header's chip and opens the update window,
unless that version was set to "don't remind me". Install now downloads and
checks it on a worker thread, hands the swap to a helper and closes the app.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication

import updater
import whats_new
from config_manager import PROFILE_COUNT, ConfigManager
from console_window import ConsoleWindow
from constants import (
    APP_NAME,
    BURST_DURATION,
    BURST_INTERVAL,
    CLICK_ACTIONS,
    DEFAULT_CLICK_ACTION,
    DEFAULT_HIDE_CONSOLE,
    DEFAULT_OSC_ROUTER_518,
    DEFAULT_PRESERVE_HEIGHT_ON_AVATAR,
    DEFAULT_SEND_RATE,
    DEFAULT_HOTKEY_SPEED,
    DEFAULT_HOTKEY_SPEED_UNIT,
    DEFAULT_HOTKEYS_ENABLED,
    DEFAULT_SETTINGS_OPEN,
    DEFAULT_STARTUP_HEIGHT_CM,
    DEFAULT_TRANSITION_DURATION,
    DEFAULT_TRANSITION_TARGET_CM,
    DEFAULT_TRANSITION_UNIT,
    ECHO_HOLD_S,
    HOTKEY_SPEED_MAX_CM,
    HOTKEY_SPEED_MAX_PCT,
    HOTKEY_SPEED_MIN,
    MAX_HEIGHT_CM,
    MIN_HEIGHT_CM,
    PRESERVE_MAX_RETRIES,
    PRESERVE_TOLERANCE_CM,
    SEND_RATES,
    TRANSITION_MAX_DURATION_S,
    TRANSITION_MIN_DURATION_S,
    TRANSITION_MIN_STEP_CM,
    UNLOCKED_MAX_HEIGHT_CM,
)
from height_logic import (
    CURVE_LINEAR,
    CURVE_SCALE,
    CURVES,
    SPEED_CM,
    SPEED_UNITS,
    HeightHistory,
    MenuInput,
    ReportGate,
    Transition,
    check_range,
    check_write,
    describe_duration,
    format_duration,
    format_height,
    hold_height,
    is_number,
    max_height_cm,
    reported_cm,
    same_height,
)
from hotkeys import DEFAULT_GROW, DEFAULT_SHRINK, Hotkey, KeyReader, key_name
from osc.manager import VRChatOSCManager
from osc.router518 import ROUTER, Router518KeepAlive
from ui import theme
from ui.window import HeightShiftWindow

logger = logging.getLogger(__name__)

# One clock for every timestamp that gets compared, here and in the OSC
# manager: high resolution (unlike time.monotonic's ~16 ms on Windows) and
# the same in every thread.
now = time.perf_counter

# Reading the height over HTTP: how often to try before waiting for VRChat to
# push it (it does on every change), and the delay before the first try.
QUERY_MAX_ATTEMPTS = 12          # backoff 0.5, 1, 2, 4, then 5 s: about 40 s in all
QUERY_FIRST_DELAY_MS = 300
QUERY_AFTER_AVATAR_CHANGE_MS = 2000   # VRChat needs a moment to load the new avatar


def _speed_max(unit: str) -> float:
    return HOTKEY_SPEED_MAX_CM if unit == SPEED_CM else HOTKEY_SPEED_MAX_PCT


class HeightShiftController(QObject):
    """Wires the window, the OSC manager and the config together.

    OSC events arrive on background threads; the signals below carry them
    (with the time they were RECEIVED) onto the UI thread.
    """

    _sig_height = Signal(float, float)        # metres, receive time
    _sig_avatar = Signal(str, float)          # avatar id, receive time
    _sig_connected = Signal()
    _sig_disconnected = Signal()
    _sig_query_missed = Signal(int, int)      # read round, attempt that found nothing
    _sig_menu = Signal(str, object, float)    # menu parameter, value, receive time
    _sig_menu_present = Signal(int, object)   # check round, True / False / None
    _sig_update_checked = Signal(object, bool)   # release info or None, asked by hand
    _sig_update_progress = Signal(int, int)      # downloaded bytes, total (0 = unknown)
    _sig_update_downloaded = Signal(str)         # the verified exe, "" when it failed
    activate_requested = Signal()                  # a second launch was attempted

    def __init__(self, window: HeightShiftWindow, config: ConfigManager,
                 console: ConsoleWindow):
        super().__init__()
        self.window = window
        self.config = config
        self.console = console

        # --- settings (typed + validated; bad stored values fall back) ---
        c = config
        self.unlocked = c.get_bool("unlock_upper_limit", False)
        top = max_height_cm(self.unlocked)
        self.preserve = c.get_bool("preserve_height_on_avatar_switch",
                                   DEFAULT_PRESERVE_HEIGHT_ON_AVATAR)
        self.hide_console = c.get_bool("hide_console", DEFAULT_HIDE_CONSOLE)
        self.router_on = c.get_bool("osc_router_518", DEFAULT_OSC_ROUTER_518)
        self.startup_mode = c.get_choice("startup_mode", "query", ("query", "fixed_height"))
        self.startup_height = min(top, c.get_number(
            "startup_height", DEFAULT_STARTUP_HEIGHT_CM, MIN_HEIGHT_CM, UNLOCKED_MAX_HEIGHT_CM))
        lo = c.get_number("slider_min_value", MIN_HEIGHT_CM, MIN_HEIGHT_CM, top)
        hi = c.get_number("slider_max_value", MAX_HEIGHT_CM, MIN_HEIGHT_CM, top)
        if lo >= hi:
            lo, hi = float(MIN_HEIGHT_CM), float(MAX_HEIGHT_CM)
        self.slider_lo, self.slider_hi = lo, hi
        self.profiles = c.load_profiles()
        # what a click does: on each saved height, and on the height scale
        raw = c.config.get("profile_actions")
        raw = raw if isinstance(raw, dict) else {}
        self.slot_actions = {
            i: raw.get(f"profile{i}") if raw.get(f"profile{i}") in CLICK_ACTIONS
            else DEFAULT_CLICK_ACTION for i in range(1, PROFILE_COUNT + 1)}
        self.scale_mode = c.get_choice("scale_mode", DEFAULT_CLICK_ACTION, CLICK_ACTIONS)
        self.hotkeys_on = c.get_bool("hotkeys_enabled", DEFAULT_HOTKEYS_ENABLED)
        self.hotkeys_vrchat_only = c.get_bool("hotkeys_vrchat_only", True)
        self.hotkey_grow = Hotkey.from_config(c.config.get("hotkey_grow")) or DEFAULT_GROW
        self.hotkey_shrink = Hotkey.from_config(c.config.get("hotkey_shrink")) or DEFAULT_SHRINK
        if self.hotkey_grow == self.hotkey_shrink:
            self.hotkey_grow, self.hotkey_shrink = DEFAULT_GROW, DEFAULT_SHRINK
        self.hotkey_unit = c.get_choice("hotkey_speed_unit", DEFAULT_HOTKEY_SPEED_UNIT, SPEED_UNITS)
        self.hotkey_speed = c.get_number("hotkey_speed", DEFAULT_HOTKEY_SPEED, HOTKEY_SPEED_MIN,
                                         _speed_max(self.hotkey_unit))
        # how many times a second a transition or a held key sends the height
        self.send_rate = c.get_choice("send_rate", DEFAULT_SEND_RATE, SEND_RATES)

        # --- what VRChat's avatar is at, as far as we know ---------------
        self.height_cm: Optional[float] = None     # None = not read yet
        self.height_note = ""                      # where it came from
        self.history = HeightHistory()
        self.gate = ReportGate()
        self._release_timer = self._single_shot(self._on_release)

        self._fixed_applied = False                # fixed startup height: once per run
        self._query_round = 0                      # bumped by _start_reading
        self._query_attempts = 0

        # --- preserve burst ----------------------------------------------
        self._burst_timer = QTimer(self)
        self._burst_timer.setInterval(int(BURST_INTERVAL * 1000))
        self._burst_timer.timeout.connect(self._burst_tick)
        self._burst_target: Optional[float] = None   # None + transition = follow it
        self._burst_left = 0
        self._burst_retries = 0
        self._burst_follows_transition = False
        self._verify_timer = self._single_shot(self._verify_preserve)

        # --- slow transition ---------------------------------------------
        self.transition: Optional[Transition] = None
        self._tick_timer = QTimer(self)
        self._tick_timer.setTimerType(Qt.PreciseTimer)

        self._tick_timer.timeout.connect(self._transition_tick)
        self._last_tick_sent: Optional[float] = None

        # --- hold-to-grow hotkeys -----------------------------------------
        # Polled, never hooked (see hotkeys.py). While a key is held the height
        # follows height_logic.hold_height from where the hold started.
        self.keys = KeyReader()
        self._hotkey_timer = QTimer(self)
        self._hotkey_timer.setTimerType(Qt.PreciseTimer)
        self._apply_send_rate()
        self._hotkey_timer.timeout.connect(self._hotkey_tick)
        self._hold_dir = 0                          # +1 grow, -1 shrink, 0 none
        self._hold_base: Optional[float] = None     # None: this hold sends nothing
        self._hold_t0 = 0.0
        self._hold_last: Optional[float] = None     # last height this hold sent
        self._hold_at_bound = False                 # said "at the limit" already
        self._hold_source = "hotkey"                # or "VRChat menu"

        # --- the in-VRChat menu --------------------------------------------
        self.menu = MenuInput()
        self._menu_present: Optional[bool] = None   # does this avatar have it?
        self._menu_round = 0                        # bumped by _check_menu

        # --- OSC ---------------------------------------------------------
        # The manager stamps what it receives with OUR clock, at the moment it
        # arrived (or, for an HTTP read, the moment it was asked for).
        self.osc = VRChatOSCManager(log_dir=os.path.dirname(config.config_file) or None,
                                    clock=now)
        self.osc.on_connected = lambda _ports: self._sig_connected.emit()
        self.osc.on_disconnected = lambda: self._sig_disconnected.emit()
        self.osc.on_height_received = lambda m, t: self._sig_height.emit(float(m), float(t))
        self.osc.on_avatar_change = lambda aid, t: self._sig_avatar.emit(str(aid), float(t))
        self.osc.on_menu_parameter = (
            lambda name, value, t: self._sig_menu.emit(str(name), value, float(t)))

        # 518 router fallback (see 518Hub docs/STANDARD.md). The OSC receive
        # port binds lazily once VRChat is discovered, so the getter re-reads
        # it each tick — 0 just parks the keep-alive until then.
        self.router518 = Router518KeepAlive(
            lambda: getattr(self.osc, "local_listen_port", 0), name=APP_NAME)

        q = Qt.QueuedConnection
        self._sig_height.connect(self._on_reported, q)
        self._sig_avatar.connect(self._on_avatar_change, q)
        self._sig_connected.connect(self._on_connected, q)
        self._sig_disconnected.connect(self._on_disconnected, q)
        self._sig_query_missed.connect(self._on_query_missed, q)
        self._sig_menu.connect(self._on_menu, q)
        self._sig_menu_present.connect(self._on_menu_present, q)
        self.activate_requested.connect(self.window.bring_to_front, q)

        self._wire_ui()
        self._populate()
        if self.hide_console and console.available:
            QTimer.singleShot(50, lambda: console.set_hidden(True))
        self.window.set_close_handler(self.stop)

    def _single_shot(self, slot) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(slot)
        return timer

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def _wire_ui(self) -> None:
        w = self.window
        w.adjust_clicked.connect(self._on_adjust)
        w.refresh_clicked.connect(self._on_refresh)
        w.profile_save.connect(self._on_profile_save)
        w.go_instant_clicked.connect(self._on_go_instant)
        w.play_clicked.connect(self._on_play)
        w.pause_clicked.connect(self._on_pause)
        w.stop_clicked.connect(lambda: self._stop_transition(stopped_by="Stop"))
        w.transition_inputs_changed.connect(self._on_transition_inputs)
        w.preserve_toggled.connect(self._on_preserve)
        w.unlock_toggled.connect(self._on_unlock)
        w.send_rate_changed.connect(self._on_send_rate)
        w.router_toggled.connect(self._on_router)
        w.hide_console_toggled.connect(self._on_hide_console)
        w.startup_mode_changed.connect(self._on_startup_mode)
        w.startup_height_changed.connect(self._on_startup_height)
        w.slider_range_changed.connect(self._on_slider_range)
        w.ui_mode_changed.connect(self._on_ui_mode)
        w.text_scale_changed.connect(self._on_text_scale)
        w.settings_toggled.connect(lambda on: self.config.update_config({"settings_open": on}))
        w.geometry_changed.connect(self._save_geometry)
        w.hotkeys_toggled.connect(self._on_hotkeys_toggled)
        w.hotkey_captured.connect(self._on_hotkey_captured)
        w.hotkey_speed_changed.connect(self._on_hotkey_speed)
        w.hotkeys_vrchat_only_toggled.connect(self._on_hotkeys_vrchat_only)
        w.slot_action_changed.connect(self._on_slot_action)
        w.scale_mode_changed.connect(self._on_scale_mode)
        w.update_chip_clicked.connect(self._open_update)
        w.check_updates_clicked.connect(lambda: self.check_for_updates(manual=True))
        w.update_install_clicked.connect(self._on_update_install)
        w.update_skipped.connect(self._on_update_skipped)
        w.whats_new_clicked.connect(self._on_whats_new)
        self._sig_update_checked.connect(self._on_update_checked)
        self._sig_update_progress.connect(w.set_update_progress)
        self._sig_update_downloaded.connect(self._on_update_downloaded)

    def _populate(self) -> None:
        w, c = self.window, self.config
        top = max_height_cm(self.unlocked)
        w.set_target_limit(top)
        w.set_slider_range(self.slider_lo, self.slider_hi, top)
        w.set_preserve(self.preserve)
        w.set_unlock(self.unlocked)
        w.set_send_rate(self.send_rate)
        w.set_router(self.router_on)
        w.set_hide_console(self.hide_console, self.console.available)
        w.set_startup(self.startup_mode, self.startup_height)
        w.set_ui_mode(theme.mode())
        w.set_text_scale(theme.text_scale())
        w.set_settings_open(c.get_bool("settings_open", DEFAULT_SETTINGS_OPEN))
        w.set_transition_inputs(
            min(top, c.get_number("transition_target_cm", DEFAULT_TRANSITION_TARGET_CM,
                                  MIN_HEIGHT_CM, UNLOCKED_MAX_HEIGHT_CM)),
            int(c.get_number("transition_duration", DEFAULT_TRANSITION_DURATION, 1, 999)),
            c.get_choice("transition_unit", DEFAULT_TRANSITION_UNIT, ("s", "min", "h")),
            c.get_choice("transition_curve", CURVE_LINEAR, CURVES),
        )
        for i in range(1, PROFILE_COUNT + 1):
            w.set_profile(i, self.profiles.get(f"profile{i}"))
        for i, action in self.slot_actions.items():
            w.set_slot_action(i, action)
        w.set_scale_mode(self.scale_mode)
        self._show_hotkeys()
        self._show_menu_status()
        w.set_updates_info(updater.is_self_updatable())
        w.set_connection(False)
        w.set_ports(None, None)
        self._show_height()
        self._refresh()
        w.status("Looking for VRChat…")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self.osc.start()
        if self.router_on:
            self.router518.start()
        self._sync_hotkey_timer()

    # ------------------------------------------------------------------
    # Updates (updater.py)
    # ------------------------------------------------------------------

    def check_for_updates(self, version: Optional[str] = None, manual: bool = False) -> None:
        """Ask GitHub on a worker thread (main.py: once at start, with the
        running version; Settings: by hand). Never blocks, never raises."""
        if version:
            self._app_version = version
        current = getattr(self, "_app_version", None)
        if not current:
            return
        if manual:
            self.window.set_update_check_state("Asking GitHub…")

        def worker() -> None:
            self._sig_update_checked.emit(updater.check_for_update(current), manual)
        threading.Thread(target=worker, name="update-check", daemon=True).start()

    def _on_update_checked(self, info: Optional[dict], manual: bool) -> None:
        w = self.window
        if info and info.get("available"):
            self._update_info = info
            w.set_update_available(info["tag"])
            # the start's check stays quiet about a version set to "don't
            # remind me"; asking by hand always shows the window
            if manual or self.config.get_str("skip_update_version") != info["tag"]:
                self._open_update()
        if manual:
            w.set_update_check_state(
                "Couldn't reach GitHub — try again later." if info is None else
                f"{info['tag']} is available." if info.get("available") else
                "You're up to date.")

    def _can_install(self) -> bool:
        info = getattr(self, "_update_info", None)
        return bool(info and info.get("asset")) and updater.is_self_updatable()

    def _open_update(self) -> None:
        info = getattr(self, "_update_info", None)
        if info:
            self.window.show_update_dialog(info, self._can_install())

    def _on_update_skipped(self, tag: str) -> None:
        self.config.update_config({"skip_update_version": tag})
        self.window.set_update_available(None)

    # ------------------------------------------------------------------
    # What's new (whats_new.py; OscGoesPurrr's design)
    # ------------------------------------------------------------------

    def whats_new_on_launch(self, version: str) -> bool:
        """After an update: the notes of every release this install hasn't
        seen, once. A first install starts "up to date" without a window.
        True when the window was opened."""
        self._app_version = getattr(self, "_app_version", None) or version
        seen = self.config.get_str(whats_new.SEEN_KEY)
        fresh = bool(getattr(self.config, "created_fresh", False))
        releases = [] if fresh else whats_new.unseen_releases(seen, version)
        newest = whats_new.releases_for(version)
        if newest and newest[0].version != seen:
            self.config.update_config({whats_new.SEEN_KEY: newest[0].version})
        if not releases:
            return False
        self.window.show_whats_new(whats_new.as_plain(releases))
        return True

    def _on_whats_new(self) -> None:
        """Settings → Updates → What's new: every release's notes this
        build has."""
        version = getattr(self, "_app_version", None)
        releases = whats_new.releases_for(version) if version else list(whats_new.RELEASES)
        self.window.show_whats_new(whats_new.as_plain(releases))

    def _on_update_install(self) -> None:
        asset = (getattr(self, "_update_info", None) or {}).get("asset")
        if not asset or not updater.is_self_updatable():
            self.window.set_update_failed("This copy can't install it — get it from the "
                                          "release page.")
            return
        logger.info(f"Downloading update {self._update_info.get('tag')}")

        def worker() -> None:
            path = updater.download_update(
                asset, progress=lambda done, total: self._sig_update_progress.emit(done, total))
            self._sig_update_downloaded.emit(path or "")
        threading.Thread(target=worker, name="update-download", daemon=True).start()

    def _on_update_downloaded(self, path: str) -> None:
        w = self.window
        if not path:
            w.set_update_failed("The download failed or didn't check out — nothing was "
                                "changed. Try again, or get it from the release page.")
            return
        if not updater.apply_update(path):
            w.set_update_failed("Couldn't start the installer — nothing was changed. "
                                f"The new version was saved to {path}")
            return
        logger.info("Update checked; closing so the new version can take over")
        if updater.relaunch_after_apply():
            updater.relaunch_when_gone()      # Linux: the new AppImage, once we're gone
        w.set_update_installing()
        # closeEvent -> stop(); once this process is gone the helper replaces
        # the exe and starts the new one
        w.close()

    def stop(self) -> None:
        self._tick_timer.stop()
        self._burst_timer.stop()
        self._hotkey_timer.stop()
        self._save_geometry()
        try:
            self.router518.stop()
        except Exception as e:
            logger.warning(f"Router 518 stop error: {e}")
        try:
            self.osc.stop()
        except Exception as e:
            logger.warning(f"OSC manager stop error: {e}")

    # ------------------------------------------------------------------
    # THE write path
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return bool(self.osc.is_connected)

    def _write(self, cm: float, why: str, note: str, *, quiet: bool = False) -> bool:
        """The only place a height is sent. True if it actually went out."""
        if not self.connected:
            if not quiet:
                self._status(f"Not sent ({why}): VRChat isn't connected.")
            return False
        err = check_write(cm, self.unlocked)
        if err:
            shown = format_height(cm) if is_number(cm) else repr(cm)
            self._status(f"Not sent ({why}): {shown} is {err}.", warn=True)
            return False
        if not self.osc.send_height(cm):
            if not quiet:
                self._status(f"Sending {format_height(cm)} failed — see osc_diagnostics.log.",
                             warn=True)
            return False
        t = now()
        self.gate.on_send(t)
        self.history.record(t, float(cm), "app")
        self._release_timer.start(int(ECHO_HOLD_S * 1000) + 20)
        self.height_cm = float(cm)
        self.height_note = note
        self._show_height()
        return True

    def _take_over(self, what: str) -> None:
        """A manual change ends whatever else was driving the height, so the
        two can never fight (the old burst kept resending the old height
        over a click made during it)."""
        if self.transition is not None:
            self._stop_transition(stopped_by=what)
        self._cancel_burst()

    def _set_absolute(self, cm: float, why: str) -> None:
        err = check_write(cm, self.unlocked)
        if err:
            self._status(f"Not sent ({why}): {format_height(cm)} is {err}.", warn=True)
            return
        self._take_over(why)
        if self._write(cm, why, "set by HeightShift"):
            self._status(f"Set {format_height(cm)} ({why}).")
        self._refresh()

    # ------------------------------------------------------------------
    # THE read path
    # ------------------------------------------------------------------

    def _on_reported(self, meters: float, seen_at: float) -> None:
        """A height from VRChat: an OSC packet (seen when it arrived) or an
        HTTP read (seen when it was asked for)."""
        cm = reported_cm(meters)
        if cm is None:
            logger.warning(f"Ignored an unusable height from VRChat: {meters!r}")
            return
        self.history.record(seen_at, cm, "vrchat")
        adopt = self.gate.offer(seen_at, now(), cm)
        if adopt is not None:
            self._adopt(adopt)
        elif self.gate.holding and not self._release_timer.isActive():
            self._release_timer.start(max(0, int((self.gate.hold_until - now()) * 1000)) + 20)

    def _on_release(self) -> None:
        t = now()
        if t < self.gate.hold_until:          # a later send extended the hold
            self._release_timer.start(int((self.gate.hold_until - t) * 1000) + 20)
            return
        value = self.gate.release(t)
        if value is not None:
            self._adopt(value)

    def _adopt(self, cm: float) -> None:
        first = self.height_cm is None
        changed = not same_height(self.height_cm, cm)
        self.height_cm = cm
        self.height_note = "read from VRChat"
        self._show_height()
        if first:
            self._status(f"Read {format_height(cm)} from VRChat.")
        elif changed:
            self._status(f"VRChat reports {format_height(cm)}.")
        self._refresh()

    # ------------------------------------------------------------------
    # OSC events
    # ------------------------------------------------------------------

    def _on_connected(self) -> None:
        ports = self.osc.ports
        self.window.set_connection(True)
        self.window.set_ports(ports.get("local_listen_port"), ports.get("udp_send_port"))
        self._last_tick_sent = None      # a running transition resends at once
        if self.startup_mode == "fixed_height" and not self._fixed_applied:
            # Once per app run, the first time VRChat connects — no matter how
            # late (the old 10 s timeout dropped it if VRChat started later).
            self._fixed_applied = True
            if self._write(self.startup_height, "fixed startup height", "fixed startup height"):
                self._status(f"Connected — set the fixed startup height "
                             f"{format_height(self.startup_height)}.")
        else:
            self._status("Connected to VRChat.")
            if self.height_cm is None:
                self._start_reading(QUERY_FIRST_DELAY_MS)
        self._check_menu(QUERY_FIRST_DELAY_MS)
        self._show_menu_status()                   # "checking…" until VRChat answers
        self._show_height()
        self._refresh()

    def _on_disconnected(self) -> None:
        self.window.set_connection(False)
        self.window.set_ports(None, None)
        self._cancel_burst()
        # VRChat may have restarted with the avatar at its default height: what
        # we knew is stale, and a step from it would write a wrong value.
        self.height_cm = None
        self.history.clear()
        self.gate.reset()
        self._release_timer.stop()
        # A key held through the disconnect sends nothing more: its starting
        # height is stale too. Let go and press again once the height is back.
        self._hold_base = None
        self.menu.reset()                    # a menu button can't be held without VRChat
        self._menu_present = None
        self._menu_round += 1
        self._show_menu_status()
        self._sync_hotkey_timer()
        note = ""
        if self.transition is not None and self.transition.playing:
            note = " The transition keeps its schedule and resumes sending then."
        self._status("VRChat disconnected — waiting for it to come back." + note)
        self._show_height()
        self._refresh()

    def _on_avatar_change(self, avatar_id: str, changed_at: float) -> None:
        logger.info(f"Avatar change: {avatar_id!r}")
        # Whatever VRChat said before this moment describes the OLD avatar —
        # including an HTTP read that is still on its way.
        self.gate.on_avatar_change(changed_at)
        # The menu closed with the old avatar: a Grow held in it is let go.
        self.menu.on_avatar_change(changed_at)
        if self._hotkey_timer.isActive():
            self._hotkey_tick()
        self._menu_present = None
        self._check_menu(QUERY_AFTER_AVATAR_CHANGE_MS)
        self._show_menu_status()
        if self._holding:
            # The held key owns the height and resends it ten times a second
            # anyway, onto the new avatar too: no burst to fight it.
            self._status("Avatar changed — the held key carries on.")
            return
        t = self.transition
        if t is not None and t.playing:
            # The transition owns the height: resend its value now, and keep
            # resending it through the swap if preserving is on.
            self._last_tick_sent = None
            if self.preserve:
                self._start_burst(None, retries=0)
            self._status("Avatar changed — the transition carries on.")
            return
        if self.preserve:
            target = self.history.preserve_target(changed_at)
            if target is not None:
                self._start_burst(target, retries=PRESERVE_MAX_RETRIES)
                self._status(f"Avatar changed — keeping {format_height(target)}.")
                return
            logger.info("Avatar changed before any height was known: nothing to keep.")
        self._cancel_burst()
        self.height_cm = None
        self._show_height()
        self._refresh()
        self._status("Avatar changed — reading the new avatar's height.")
        self._start_reading(QUERY_AFTER_AVATAR_CHANGE_MS)

    # ------------------------------------------------------------------
    # Reading the height over HTTP (OSCQuery)
    # ------------------------------------------------------------------

    def _start_reading(self, delay_ms: int) -> None:
        """Start a fresh round of HTTP reads; an older round still waiting
        for its next try stops (quick avatar swaps used to stack them)."""
        self._query_round += 1
        self._query_attempts = 0
        round_ = self._query_round
        QTimer.singleShot(delay_ms, lambda: self._query_height(round_))

    def _query_height(self, round_: int) -> None:
        if round_ != self._query_round or self.height_cm is not None or not self.connected:
            return
        self._query_attempts += 1
        attempt = self._query_attempts

        def worker() -> None:
            result = self.osc.read_height()     # (metres, asked_at) or None
            # Back to the UI thread through signals: a QTimer started on this
            # plain Python thread would never fire (no event loop here). The
            # old code did exactly that, so its retries never ran.
            if result is not None:
                self._sig_height.emit(float(result[0]), float(result[1]))
            else:
                self._sig_query_missed.emit(round_, attempt)

        threading.Thread(target=worker, daemon=True, name="HeightQuery").start()

    def _on_query_missed(self, round_: int, attempt: int) -> None:
        if round_ != self._query_round or self.height_cm is not None or not self.connected:
            return
        if attempt >= QUERY_MAX_ATTEMPTS:
            logger.info(f"Gave up reading the height after {attempt} tries; "
                        "VRChat pushes it over OSC when it changes.")
            self._status("VRChat hasn't told us the height yet — it arrives with the "
                         "next change, or press ↻.")
            return
        delay_ms = min(5000, 500 * (2 ** min(attempt - 1, 4)))
        QTimer.singleShot(delay_ms, lambda: self._query_height(round_))

    # ------------------------------------------------------------------
    # Preserve height across avatar changes
    # ------------------------------------------------------------------

    def _start_burst(self, target: Optional[float], retries: int) -> None:
        self._burst_target = target
        self._burst_follows_transition = target is None
        self._burst_left = max(1, int(round(BURST_DURATION / BURST_INTERVAL)))
        self._burst_retries = retries
        self._verify_timer.stop()
        self._burst_timer.start()
        self._burst_tick()
        self._refresh_activity()

    def _burst_value(self) -> Optional[float]:
        if not self._burst_follows_transition:
            return self._burst_target
        t = self.transition
        if t is not None and t.playing:
            return t.end_cm if t.finished(now()) else t.value(now())
        return None

    def _burst_tick(self) -> None:
        value = self._burst_value()
        if value is None or not self.connected:
            self._cancel_burst()
            return
        note = "transition" if self._burst_follows_transition else "kept after avatar change"
        if not self._write(value, "keeping height after avatar change", note, quiet=True):
            self._cancel_burst()
            return
        if self._burst_follows_transition:
            self._last_tick_sent = value
        self._burst_left -= 1
        if self._burst_left <= 0:
            self._burst_timer.stop()
            if self._burst_follows_transition:
                self._finish_burst()
            else:
                # Check once VRChat's echo has settled whether it stuck.
                self._verify_timer.start(int((ECHO_HOLD_S + 0.3) * 1000))
            self._refresh_activity()

    def _verify_preserve(self) -> None:
        target = self._burst_target
        if target is None or not self.connected:
            self._finish_burst()
            return
        if (self.height_cm is not None
                and abs(self.height_cm - target) > PRESERVE_TOLERANCE_CM):
            if self._burst_retries > 0:
                logger.info(f"VRChat reports {format_height(self.height_cm)} after the burst "
                            f"— one more burst for {format_height(target)}.")
                self._start_burst(target, self._burst_retries - 1)
                return
            self._status(f"VRChat kept {format_height(self.height_cm)} instead of "
                         f"{format_height(target)} — this world may not allow scaling.",
                         warn=True)
        self._finish_burst()

    def _finish_burst(self) -> None:
        self._burst_target = None
        self._burst_follows_transition = False
        self._burst_left = 0
        self._refresh_activity()

    def _cancel_burst(self) -> None:
        self._burst_timer.stop()
        self._verify_timer.stop()
        self._finish_burst()

    # ------------------------------------------------------------------
    # Slow transition
    # ------------------------------------------------------------------

    def _inputs(self):
        target, value, unit, curve = self.window.transition_inputs()
        seconds = self.window.duration_seconds(value, unit)
        seconds = min(TRANSITION_MAX_DURATION_S, max(TRANSITION_MIN_DURATION_S, seconds))
        return target, seconds, curve, value, unit

    def _play_blocker(self) -> str:
        """Why Play can't start right now ('' = it can)."""
        if not self.connected:
            return "Waiting for VRChat."
        if self.height_cm is None:
            return "Waiting for VRChat's current height — the transition starts from it."
        if self._holding:
            if self._hold_source == "hotkey":
                return "Let go of the hotkey first."
            return "Let go of Grow / Shrink in the VRChat menu first."
        target, _secs, _curve, _v, _u = self._inputs()
        err = check_write(target, self.unlocked)
        if err:
            return f"The target {format_height(target)} is {err}."
        err = check_write(self.height_cm, self.unlocked)
        if err:
            return f"The current height {format_height(self.height_cm)} is {err}."
        if same_height(target, self.height_cm):
            return "Already at the target height."
        return ""

    def _on_play(self) -> None:
        t = self.transition
        if t is not None and not t.playing:          # resume
            t.play(now())
            self._last_tick_sent = None
            self._tick_timer.start()
            self._status(f"Transition resumed — {format_duration(t.remaining(now()))} left.")
            self._transition_tick()
            return
        blocker = self._play_blocker()
        if blocker:
            self._status(f"Can't start: {blocker}", warn=True)
            self._refresh()
            return
        target, seconds, curve, _v, _u = self._inputs()
        self._cancel_burst()
        self.transition = Transition(self.height_cm, target, seconds, curve)
        self.transition.play(now())
        self._last_tick_sent = self.height_cm       # the start height is already there
        self._tick_timer.start()
        self._status(f"Transition: {format_height(self.height_cm)} → "
                     f"{format_height(target)} over {describe_duration(seconds)}.")
        self._refresh()

    def _on_pause(self) -> None:
        t = self.transition
        if t is None or not t.playing:
            return
        t.pause(now())
        self._tick_timer.stop()
        self._status(f"Transition paused at {format_height(self.height_cm or t.value(now()))}.")
        self._refresh()

    def _stop_transition(self, stopped_by: str = "") -> None:
        t = self.transition
        if t is None:
            return
        self.transition = None
        self._tick_timer.stop()
        if self._burst_follows_transition:
            self._cancel_burst()
        where = format_height(self.height_cm) if self.height_cm is not None else "its last height"
        reason = f" ({stopped_by})" if stopped_by and stopped_by != "Stop" else ""
        self._status(f"Transition stopped at {where}{reason}.")
        self._refresh()

    def _transition_tick(self) -> None:
        t = self.transition
        if t is None or not t.playing:
            self._tick_timer.stop()
            return
        n = now()
        finished = t.finished(n)
        value = t.end_cm if finished else t.value(n)
        err = check_write(value, self.unlocked)
        if err:
            self.transition = None
            self._tick_timer.stop()
            self._status(f"Transition stopped: {format_height(value)} is {err}.", warn=True)
            self._refresh()
            return
        sent_end = False
        if self.connected and self._burst_left == 0:
            due = (finished or self._last_tick_sent is None
                   or abs(value - self._last_tick_sent) >= TRANSITION_MIN_STEP_CM)
            if due and self._write(value, "transition", "transition", quiet=True):
                self._last_tick_sent = value
                sent_end = finished
        elif self._burst_left > 0 and finished:
            sent_end = same_height(self._last_tick_sent, t.end_cm)
        if finished and sent_end:
            self.transition = None
            self._tick_timer.stop()
            self._status(f"Transition done — reached {format_height(t.end_cm)}.")
            self._refresh()
            return
        # Not connected at the end: keep ticking, the end height goes out as
        # soon as VRChat is back.
        self._refresh_transition()

    def _on_transition_inputs(self) -> None:
        target, _secs, curve, value, unit = self._inputs()
        self.config.update_config({
            "transition_target_cm": target,
            "transition_duration": value,
            "transition_unit": unit,
            "transition_curve": curve,
        })
        self._refresh()

    # ------------------------------------------------------------------
    # Hold-to-grow hotkeys
    # ------------------------------------------------------------------

    @property
    def _holding(self) -> bool:
        """A key is held AND this hold is sending (it has a starting height)."""
        return self._hold_dir != 0 and self._hold_base is not None

    def _hold_wanted(self) -> bool:
        """The hold timer runs while hotkeys are on, or a menu button is held."""
        return (self.hotkeys_on and self.keys.available) or any(self.menu.held.values())

    def _sync_hotkey_timer(self) -> None:
        if self._hold_wanted():
            if not self._hotkey_timer.isActive():
                self._hotkey_timer.start()
        else:
            self._hotkey_timer.stop()
            self._hold_change(0)

    def _keys_held(self):
        """(grow, shrink) as the keyboard has them, if the hotkeys may act."""
        if not (self.hotkeys_on and self.keys.available) or self.window.capturing_key:
            return False, False
        if self.hotkeys_vrchat_only and not self.keys.vrchat_in_front():
            return False, False
        return self.keys.is_held(self.hotkey_grow), self.keys.is_held(self.hotkey_shrink)

    def _held_direction(self) -> int:
        key_grow, key_shrink = self._keys_held()
        grow = key_grow or self.menu.held["grow"]
        shrink = key_shrink or self.menu.held["shrink"]
        return int(grow) - int(shrink)          # both held: nothing

    def _hotkey_tick(self) -> None:
        direction = self._held_direction()
        if direction != self._hold_dir:
            self._hold_change(direction)
        if self._holding:
            self._hold_step()
        if self._hold_dir == 0 and not self._hold_wanted():
            self._hotkey_timer.stop()           # the menu let go, no hotkeys to watch

    def _hold_change(self, direction: int) -> None:
        """A key went down, came up, or the other one took over."""
        was_holding, old = self._holding, self._hold_dir
        self._hold_dir = direction
        self._hold_base = None
        if was_holding and self._hold_last is not None:
            self._status(f"{'Grew' if old > 0 else 'Shrank'} to "
                         f"{format_height(self._hold_last)} ({self._hold_source}).")
        self._hold_last = None
        self._hold_at_bound = False
        if direction:
            from_menu = self.menu.held["grow" if direction > 0 else "shrink"]
            self._hold_source = "VRChat menu" if from_menu else "hotkey"
            what = "Growing" if direction > 0 else "Shrinking"
            if not self.connected:
                self._status(f"{what} needs VRChat — it isn't connected.", warn=True)
            elif self.height_cm is None:
                self._status(f"{what} starts from the current height — waiting for VRChat "
                             "to report it.", warn=True)
            else:
                # A manual change: it ends a transition or an avatar-change burst.
                self._take_over(self._hold_source)
                self._hold_base = self._hold_last = self.height_cm
                self._hold_t0 = now()
                self._status(f"{what} while "
                             + ("the menu button is held…" if from_menu else "the key is held…"))
        self._refresh_activity()
        self._refresh_transition()

    def _hold_step(self) -> None:
        if not self.connected:
            return
        top = max_height_cm(self.unlocked)
        target = hold_height(self._hold_base, now() - self._hold_t0, self.hotkey_speed,
                             self.hotkey_unit, self._hold_dir)
        # A held key stops AT the limit (the limit is where the user's own
        # setting puts it), rather than having its next send refused.
        value = min(top, max(float(MIN_HEIGHT_CM), target))
        if abs(value - self._hold_last) < TRANSITION_MIN_STEP_CM:
            if value != target and not self._hold_at_bound:
                self._hold_at_bound = True
                self._status(f"At the {format_height(value)} "
                             + ("limit (tick “Unlock upper limit” to go higher)."
                                if value >= top else "minimum."))
            return
        if self._write(value, self._hold_source, self._hold_source, quiet=True):
            self._hold_last = value
            self._refresh_transition()      # the graph starts from the live height

    def _show_hotkeys(self) -> None:
        self.window.set_hotkeys(
            available=self.keys.available, enabled=self.hotkeys_on,
            grow=key_name(self.hotkey_grow), shrink=key_name(self.hotkey_shrink),
            speed=self.hotkey_speed, unit=self.hotkey_unit,
            speed_max=_speed_max(self.hotkey_unit), vrchat_only=self.hotkeys_vrchat_only)

    def _on_hotkeys_toggled(self, on: bool) -> None:
        self.hotkeys_on = bool(on)
        self.config.update_config({"hotkeys_enabled": self.hotkeys_on})
        self._sync_hotkey_timer()
        self._show_hotkeys()
        if self.hotkeys_on:
            self._status(f"Hotkeys on: hold {key_name(self.hotkey_grow)} to grow, "
                         f"{key_name(self.hotkey_shrink)} to shrink"
                         + (" while VRChat is in front." if self.hotkeys_vrchat_only else "."))

    def _on_hotkey_captured(self, which: str, vk: int, mods: int) -> None:
        hotkey = Hotkey.from_config({"vk": vk, "mods": mods})
        if hotkey is None or which not in ("grow", "shrink"):
            self._status("That key can't be a hotkey on its own.", warn=True)
            self._show_hotkeys()
            return
        other = self.hotkey_shrink if which == "grow" else self.hotkey_grow
        if hotkey == other:
            self._status(f"{key_name(hotkey)} already "
                         f"{'shrinks' if which == 'grow' else 'grows'} — pick another key.",
                         warn=True)
            self._show_hotkeys()
            return
        if which == "grow":
            self.hotkey_grow = hotkey
        else:
            self.hotkey_shrink = hotkey
        self.config.update_config({f"hotkey_{which}": hotkey.to_config()})
        self._show_hotkeys()
        self._status(f"{'Grow' if which == 'grow' else 'Shrink'} key: {key_name(hotkey)}.")

    def _on_hotkey_speed(self, speed: float, unit: str) -> None:
        if unit not in SPEED_UNITS:
            return
        self.hotkey_unit = unit
        self.hotkey_speed = min(_speed_max(unit), max(HOTKEY_SPEED_MIN, float(speed)))
        if self._holding:
            # Carry on from where the hold is now, at the new speed.
            self._hold_base, self._hold_t0 = self._hold_last, now()
        self.config.update_config({"hotkey_speed": self.hotkey_speed,
                                   "hotkey_speed_unit": self.hotkey_unit})
        self._show_hotkeys()

    def _on_hotkeys_vrchat_only(self, on: bool) -> None:
        self.hotkeys_vrchat_only = bool(on)
        self.config.update_config({"hotkeys_vrchat_only": self.hotkeys_vrchat_only})

    # ------------------------------------------------------------------
    # The in-VRChat menu
    # ------------------------------------------------------------------

    def _on_menu(self, name: str, value, seen_at: float) -> None:
        """A HeightShift menu parameter from VRChat. Whatever it does goes
        through the same paths as the window's buttons."""
        if self._menu_present is not True:
            self._menu_present = True            # it arrived, so the avatar has it
            self._show_menu_status()
        event = self.menu.offer(name, value, seen_at)
        if event is None:
            return
        kind, n = event
        if kind in ("grow", "shrink"):
            self._sync_hotkey_timer()
            self._hotkey_tick()                  # react now, not at the next tick
            return
        if kind == "play":
            t = self.transition
            if t is not None and t.playing:
                self._on_pause()
            else:
                self._on_play()
        elif kind == "stop":
            if self.transition is not None:
                self._stop_transition(stopped_by="Stop")
            else:
                self._status("VRChat menu: Stop — no transition is running.")
        elif kind == "load":
            if not 1 <= n <= PROFILE_COUNT:
                return
            if self.profiles.get(f"profile{n}") is None:
                self._status(f"VRChat menu: saved height {n} is empty.")
                return
            self._on_profile_load(n)
        elif kind == "save":
            if 1 <= n <= PROFILE_COUNT:
                self._on_profile_save(n)

    def _check_menu(self, delay_ms: int) -> None:
        """Ask VRChat (OSCQuery) whether this avatar has the menu, after
        `delay_ms`; a newer check replaces an older one still waiting."""
        self._menu_round += 1
        round_ = self._menu_round
        QTimer.singleShot(delay_ms, lambda: self._query_menu(round_))

    def _query_menu(self, round_: int) -> None:
        if round_ != self._menu_round or not self.connected:
            return
        has_menu = getattr(self.osc, "has_menu", None)
        if has_menu is None:
            return

        def worker() -> None:
            self._sig_menu_present.emit(round_, has_menu())

        threading.Thread(target=worker, daemon=True, name="MenuQuery").start()

    def _on_menu_present(self, round_: int, present) -> None:
        if round_ != self._menu_round or present is None:
            return
        if self._menu_present is True and not present:
            return          # one of its parameters arrived meanwhile: it's there
        self._menu_present = bool(present)
        self._show_menu_status()

    def _show_menu_status(self) -> None:
        self.window.set_menu_status(self.connected, self._menu_present)

    # ------------------------------------------------------------------
    # UI actions
    # ------------------------------------------------------------------

    def _on_adjust(self, delta: float) -> None:
        """A nudge stops AT the limit instead of being refused before it:
        −100 at 85 cm goes to 1 cm (as 1.x did — "I could instantly go down
        to 1 cm when someone was about to step on me"). VRChat reports in
        32-bit floats, so 2 cm arrives as 1.99999995 cm; −1 from there is 1 cm,
        not "below the minimum"."""
        if self.height_cm is None:
            self._status("Steps start from the current height — waiting for VRChat to report it.")
            return
        lo, hi = float(MIN_HEIGHT_CM), max_height_cm(self.unlocked)
        wanted = round(self.height_cm + delta, 4)
        goal = min(hi, max(lo, wanted))
        if abs(goal - self.height_cm) < 0.01:
            end = "lowest" if delta < 0 else "highest"
            self._status(f"Already at the {end} height there is: {format_height(goal)}.")
            return
        why = f"{delta:+g} cm" if goal == wanted else \
            f"{delta:+g} cm, stopped at the {'lowest' if delta < 0 else 'highest'} height"
        self._set_absolute(goal, why)

    def _on_refresh(self) -> None:
        if not self.connected:
            return
        self.height_cm = None
        self._show_height()
        self._refresh()
        self._start_reading(0)

    _ACTION_WORDS = {"select": "loads it as the target", "instant": "goes there at once",
                     "timed": "starts the timed transition there"}

    def _on_slot_action(self, num: int, action: str) -> None:
        """Saved height `num`: what a click on it does from now on."""
        if action not in CLICK_ACTIONS or not 1 <= num <= PROFILE_COUNT:
            return
        self.slot_actions[num] = action
        self.config.update_config({"profile_actions": {
            f"profile{i}": a for i, a in self.slot_actions.items()}})
        self.window.set_slot_action(num, action)
        self._status(f"Saved height {num}: a click {self._ACTION_WORDS[action]}.")

    def _on_scale_mode(self, mode: str) -> None:
        """What a click on the height scale does from now on."""
        if mode not in CLICK_ACTIONS:
            return
        self.scale_mode = mode
        self.config.update_config({"scale_mode": mode})
        self.window.set_scale_mode(mode)
        self._status(f"A click on the height scale {self._ACTION_WORDS[mode].replace('it ', '')}.")

    def _on_profile_save(self, num: int) -> None:
        if self.height_cm is None:
            self._status("Nothing to save yet — waiting for VRChat's current height.")
            return
        value = round(self.height_cm, 1)
        self.profiles[f"profile{num}"] = value
        self.config.update_config({"profiles": dict(self.profiles)})
        self.window.set_profile(num, value)
        self._status(f"Saved {format_height(value)} as profile {num}.")
        self._refresh()

    def _on_profile_load(self, num: int) -> None:
        """Saved height `num`, set at once (the VRChat menu's Load N; in the
        window a saved height is picked as the target instead)."""
        value = self.profiles.get(f"profile{num}")
        if value is None:
            return
        self._set_absolute(value, f"profile {num}")

    def _instant_blocker(self) -> str:
        """Why Go instant can't set the target right now ('' = it can)."""
        if not self.connected:
            return "Waiting for VRChat."
        if self._holding:
            return "Let go of Grow / Shrink first."
        target = self._inputs()[0]
        err = check_write(target, self.unlocked)
        if err:
            return f"The target {format_height(target)} is {err}."
        if same_height(target, self.height_cm):
            return "Already at the target height."
        return ""

    def _on_go_instant(self) -> None:
        """The target, now: no transition (a running one stops here)."""
        blocker = self._instant_blocker()
        if blocker:
            self._status(f"Can't go instantly: {blocker}", warn=True)
            self._refresh()
            return
        self._set_absolute(self._inputs()[0], "go instant")

    def _on_preserve(self, on: bool) -> None:
        self.preserve = bool(on)
        if not on:
            self._cancel_burst()
        self.config.update_config({"preserve_height_on_avatar_switch": self.preserve})

    def _on_unlock(self, on: bool) -> None:
        self.unlocked = bool(on)
        top = max_height_cm(self.unlocked)
        # Locking clamps the INPUT fields (target, fixed height, slider range)
        # to 100 m. Nothing is sent to VRChat because of it.
        self.window.set_target_limit(top)
        self.startup_height = min(self.startup_height, top)
        self.window.set_startup(self.startup_mode, self.startup_height)
        if self.slider_hi > top:
            self.slider_hi = top
            self.slider_lo = min(self.slider_lo, top - 1)
        elif self.unlocked and self.slider_hi >= MAX_HEIGHT_CM:
            # the scale's top was at the old limit: it reaches the new one
            # (a narrower range set by hand stays as it is)
            self.slider_hi = top
        self.window.set_slider_range(self.slider_lo, self.slider_hi, top)
        target, _s, curve, value, unit = self._inputs()
        self.config.update_config({
            "unlock_upper_limit": self.unlocked,
            "startup_height": self.startup_height,
            "slider_min_value": self.slider_lo,
            "slider_max_value": self.slider_hi,
            "transition_target_cm": target,
        })
        if self.unlocked:
            self._status(f"Upper limit unlocked — heights up to {format_height(top)} can be sent.")
        else:
            self._status(f"Upper limit locked — nothing above {format_height(top)} is sent.")
        self._refresh()

    def _apply_send_rate(self) -> None:
        interval = max(1, round(1000 / self.send_rate))
        self._tick_timer.setInterval(interval)       # a timed transition's sends
        self._hotkey_timer.setInterval(interval)     # a held key's (hotkey or menu)

    def _on_send_rate(self, rate: int) -> None:
        if rate not in SEND_RATES:
            return
        self.send_rate = rate
        self._apply_send_rate()
        self.config.update_config({"send_rate": rate})
        self._status(f"A transition or a held key now sends your height {rate} times a second.")

    def _on_router(self, on: bool) -> None:
        self.router_on = bool(on)
        if self.router_on:
            self.router518.start()
            logger.info(f"518 router fallback ON (subscribing at {ROUTER[0]}:{ROUTER[1]})")
        else:
            self.router518.stop()
            logger.info("518 router fallback OFF")
        self.config.update_config({"osc_router_518": self.router_on})

    def _on_hide_console(self, on: bool) -> None:
        self.hide_console = bool(on)
        self.console.set_hidden(self.hide_console)
        self.config.update_config({"hide_console": self.hide_console})

    def _on_startup_mode(self, mode: str) -> None:
        if mode in ("query", "fixed_height"):
            self.startup_mode = mode
            self.config.update_config({"startup_mode": mode})

    def _on_startup_height(self, value: float) -> None:
        if check_write(value, self.unlocked) is None:
            self.startup_height = float(value)
            self.config.update_config({"startup_height": self.startup_height})

    def _on_slider_range(self, lo: float, hi: float) -> None:
        """The height scale's MIN / MAX, from Settings or typed on the scale.
        Refused with a reason, never clamped into something else."""
        top = max_height_cm(self.unlocked)
        err = check_range(lo, hi, self.unlocked)
        if err:
            self._status(f"Scale range not changed: {err}.", warn=True)
            self.window.set_slider_range(self.slider_lo, self.slider_hi, top)
            return
        lo, hi = float(lo), float(hi)
        self.slider_lo, self.slider_hi = lo, hi
        self._status(f"Scale range: {format_height(lo)} to {format_height(hi)}.")
        self.window.set_slider_range(lo, hi, top)
        self.config.update_config({"slider_min_value": lo, "slider_max_value": hi})

    def _on_ui_mode(self, mode: str) -> None:
        theme.apply_theme(QApplication.instance(), mode_name=mode)
        self.window.set_ui_mode(theme.mode())
        self.config.update_config({"ui_mode": theme.mode()})

    def _on_text_scale(self, scale: float) -> None:
        theme.apply_theme(QApplication.instance(), scale=scale)
        self.window.set_text_scale(theme.text_scale())
        self.config.update_config({"text_scale": theme.text_scale()})

    def _save_geometry(self) -> None:
        try:
            self.config.update_config({"window_geometry_qt": self.window.geometry_b64()})
        except Exception as e:
            logger.warning(f"Could not save window geometry: {e}")

    # ------------------------------------------------------------------
    # Pushing state into the view
    # ------------------------------------------------------------------

    def _status(self, text: str, warn: bool = False) -> None:
        (logger.warning if warn else logger.info)(text)
        self.window.status(text)

    def _show_height(self) -> None:
        if self.height_cm is None:
            sub = ("reading the height from VRChat…" if self.connected
                   else "waiting for VRChat")
        else:
            sub = self.height_note
        self.window.set_height(self.height_cm, sub)

    def _refresh(self) -> None:
        known = self.height_cm is not None
        conn = self.connected
        if not conn:
            reason = "Waiting for VRChat."
        elif not known:
            reason = "Waiting for VRChat's current height — steps start from it."
        else:
            reason = ""
        self.window.set_controls_enabled(relative=conn and known, refresh=conn,
                                         reason=reason)
        # A saved height is picked as the target (nothing is sent), so it
        # needs no connection — only to be a height that may be sent.
        pick_ok = {}
        for i in range(1, PROFILE_COUNT + 1):
            value = self.profiles.get(f"profile{i}")
            if value is None:
                pick_ok[i] = (False, "Empty — the arrow below stores your current height here.")
            else:
                err = check_write(value, self.unlocked)
                pick_ok[i] = ((err is None),
                              f"{format_height(value)} is {err}." if err
                              else f"Make {format_height(value)} the target")
        self.window.set_profile_buttons(
            known, pick_ok, "Nothing to save yet — waiting for VRChat's current height.")
        self._refresh_transition()
        self._refresh_activity()

    def _refresh_transition(self) -> None:
        w = self.window
        t = self.transition
        n = now()
        if t is not None:
            remaining = t.remaining(n)
            if t.playing:
                eta = time.time() + remaining
                fmt = "%a %H:%M" if remaining > 20 * 3600 else "%H:%M"
                text = (f"Reaches {format_height(t.end_cm)} at "
                        f"{time.strftime(fmt, time.localtime(eta))} · "
                        f"{format_duration(remaining)} left")
                state = "run"
                if not self.connected:
                    text += " · waiting for VRChat"
                    state = "warn"
                w.set_transition_state("playing", True, text, state)
                w.set_target_note(f"on the way · {format_duration(remaining)} left"
                                  if self.connected else "on the way · waiting for VRChat",
                                  state)
            else:
                w.set_transition_state(
                    "paused", True,
                    f"Paused at {format_height(t.value(n))} · "
                    f"{format_duration(remaining)} left", "warn")
                w.set_target_note(f"paused · {format_duration(remaining)} left", "warn")
            w.set_graph(t.start_cm, t.end_cm, describe_duration(t.duration_s), t.curve,
                        t.progress(n))
            self._show_go_instant(t.end_cm)
            return
        target, seconds, curve, _v, _u = self._inputs()
        blocker = self._play_blocker()
        if blocker:
            text, state = blocker, ("warn" if "is above" in blocker or "is below" in blocker else "")
        else:
            eta = time.localtime(time.time() + seconds)
            text, state = (f"Would reach {format_height(target)} at "
                           f"{time.strftime('%H:%M', eta)}."), ""
        w.set_transition_state("idle", not blocker, text, state)
        w.set_graph(self.height_cm, target, describe_duration(seconds), curve, None)
        self._show_go_instant(target)
        if same_height(target, self.height_cm):
            w.set_target_note("you're there")
        else:
            w.set_target_note(f"in {describe_duration(seconds)}, "
                              f"{'even growth' if curve == CURVE_SCALE else 'even speed'}")

    def _show_go_instant(self, target: float) -> None:
        blocker = self._instant_blocker()
        self.window.set_go_instant(
            not blocker, blocker or f"Set {format_height(target)} now, without a transition"
            + (" — the running one stops here." if self.transition is not None else "."))

    def _refresh_activity(self) -> None:
        t = self.transition
        if self._holding:
            how = "key held" if self._hold_source == "hotkey" else "menu"
            self.window.set_activity(f"{'growing' if self._hold_dir > 0 else 'shrinking'} "
                                     f"({how})", "run")
        elif self._burst_left > 0 or self._verify_timer.isActive():
            self.window.set_activity("keeping height", "run")
        elif t is not None and t.playing:
            self.window.set_activity("transition running", "run")
        elif t is not None:
            self.window.set_activity("transition paused", "warn")
        else:
            self.window.set_activity("idle", "")
