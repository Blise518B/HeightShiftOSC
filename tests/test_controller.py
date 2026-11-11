"""Controller behaviour with a fake OSC manager: what does (and does not) get
written to VRChat. Runs Qt offscreen; no network, no VRChat."""

import os
import shutil
import struct
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QBoxLayout

_app = QApplication.instance() or QApplication(sys.argv)

import controller  # noqa: E402
from config_manager import ConfigManager  # noqa: E402
from constants import (  # noqa: E402
    MENU_GROW,
    MENU_LOAD,
    MENU_PLAY,
    MENU_SAVE,
    MENU_SHRINK,
    MENU_STOP,
)
from height_logic import CURVE_LINEAR, SPEED_CM  # noqa: E402
from hotkeys import DEFAULT_GROW, DEFAULT_SHRINK, MOD_CTRL, Hotkey  # noqa: E402
from ui.window import HeightShiftWindow  # noqa: E402


class FakeOSC:
    def __init__(self, log_dir=None, clock=None):
        self.is_connected = False
        self.sent = []
        self.local_listen_port = 0
        self.read_result = None            # (metres, asked_at) or None
        self.ports = {"local_listen_port": 50000, "udp_send_port": 9000}
        self.on_connected = self.on_disconnected = None
        self.on_height_received = self.on_avatar_change = None

    def start(self):
        pass

    def stop(self):
        pass

    def send_height(self, cm):
        if not self.is_connected:
            return False
        self.sent.append(round(cm, 4))
        return True

    def read_height(self):
        return self.read_result


class FakeRouter:
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass

    def stop(self):
        pass


class FakeConsole:
    available = False

    def set_hidden(self, hide):
        pass


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeKeys:
    """The keyboard: `down` holds the Hotkeys that are held right now."""

    def __init__(self, *a, **k):
        self.available = True
        self.down = set()
        self.front = "VRChat.exe"

    def is_held(self, hotkey):
        return hotkey in self.down

    def vrchat_in_front(self):
        return self.front.lower() == "vrchat.exe"


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self._orig = (controller.VRChatOSCManager, controller.Router518KeepAlive,
                      controller.now, controller.KeyReader)
        controller.VRChatOSCManager = FakeOSC
        controller.Router518KeepAlive = FakeRouter
        controller.KeyReader = FakeKeys
        self.clock = Clock()
        controller.now = self.clock
        self.tmp = tempfile.mkdtemp(prefix="hs-ctrl-")
        self.cfg_path = os.path.join(self.tmp, "c.json")

    def tearDown(self):
        (controller.VRChatOSCManager, controller.Router518KeepAlive,
         controller.now, controller.KeyReader) = self._orig
        if getattr(self, "window", None) is not None:
            self.window.set_close_handler(None)
            self.window.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, **config):
        cfg = ConfigManager(self.cfg_path)
        if config:
            cfg.update_config(config)
        self.window = HeightShiftWindow("v0 · b0", "0")
        self.c = controller.HeightShiftController(self.window, cfg, FakeConsole())
        self.osc = self.c.osc
        return self.c

    # --- helpers ------------------------------------------------------
    def connect(self):
        self.osc.is_connected = True
        self.c._on_connected()

    def report(self, meters, dt=0.0):
        self.clock.t += dt
        self.c._on_reported(meters, self.clock.t)

    def advance(self, seconds):
        self.clock.t += seconds
        if self.c._release_timer.isActive():
            self.c._on_release()

    def hold(self, hotkey, seconds, step=0.1):
        """Hold a key for `seconds`, ticking like the real 100 ms timer."""
        self.c.keys.down.add(hotkey)
        for _ in range(int(round(seconds / step))):
            self.c._hotkey_tick()
            self.clock.t += step
        self.c._hotkey_tick()

    def release(self):
        self.c.keys.down.clear()
        self.c._hotkey_tick()

    def menu(self, name, value, dt=0.3):
        """VRChat reports a HeightShift menu parameter, `dt` s from now."""
        self.clock.t += dt
        self.c._on_menu(name, value, self.clock.t)

    def tap(self, name, value=True):
        self.menu(name, value)
        self.menu(name, 0 if not isinstance(value, bool) else False, dt=0.1)

    def ticks(self, seconds, step=0.1):
        for _ in range(int(round(seconds / step))):
            self.clock.t += step
            self.c._hotkey_tick()

    # --- hold-to-grow hotkeys -------------------------------------------
    HOTKEYS = {"hotkeys_enabled": True, "hotkey_speed": 5.0, "hotkey_speed_unit": "pct"}

    def test_fresh_defaults_keys_on_cm_per_second_even_speed(self):
        self.make()
        # a timed transition over 20 s, and one saved height: slot 1 = 140 cm
        self.assertEqual(self.window.duration_spin.value(), 20)
        self.assertEqual(self.window.unit_seg.value(), "s")
        self.assertEqual(self.c.profiles, {"profile1": 140.0})
        self.assertTrue(self.c.hotkeys_on)                 # numpad + / − from the first start
        self.assertTrue(self.c.hotkeys_vrchat_only)
        self.assertEqual(self.c.hotkey_unit, SPEED_CM)
        self.assertEqual(self.c.hotkey_speed, 5.0)
        self.assertEqual(self.window.curve_seg.value(), CURVE_LINEAR)   # "Even speed"
        self.assertEqual(self.window.hotkey_unit_seg.value(), SPEED_CM)

    def test_hotkeys_off_send_nothing(self):
        self.make(hotkeys_enabled=False)
        self.connect()
        self.report(1.7)
        self.hold(DEFAULT_GROW, 1.0)
        self.assertEqual(self.osc.sent, [])

    def test_holding_grow_follows_the_speed(self):
        self.make(**self.HOTKEYS)
        self.connect()
        self.report(1.7)
        self.hold(DEFAULT_GROW, 2.0)
        sent = self.osc.sent
        self.assertEqual(len(sent), 20)                    # one per tick
        self.assertEqual(sent, sorted(sent))
        self.assertAlmostEqual(sent[-1], 170.0 * 1.05 ** 2, places=3)
        self.assertEqual(self.window.activity_chip.text(), "growing (key held)")
        self.release()
        self.assertIn("Grew to", self.window.status_msg.text())
        for _ in range(5):
            self.clock.t += 0.1
            self.c._hotkey_tick()
        self.assertEqual(len(self.osc.sent), 20)           # nothing after letting go

    def test_shrink_in_cm_per_second(self):
        self.make(hotkeys_enabled=True, hotkey_speed=10.0, hotkey_speed_unit="cm")
        self.connect()
        self.report(1.7)
        self.hold(DEFAULT_SHRINK, 1.0)
        self.assertAlmostEqual(self.osc.sent[-1], 160.0, places=3)

    def test_hold_waits_for_the_real_height(self):
        self.make(**self.HOTKEYS)
        self.connect()
        self.hold(DEFAULT_GROW, 1.0)                       # never from a 170 cm default
        self.assertEqual(self.osc.sent, [])
        self.assertIn("waiting for VRChat", self.window.status_msg.text())

    def test_only_while_vrchat_is_in_front(self):
        self.make(**self.HOTKEYS)
        self.connect()
        self.report(1.7)
        self.c.keys.front = "Discord.exe"
        self.hold(DEFAULT_GROW, 1.0)
        self.assertEqual(self.osc.sent, [])
        self.release()
        self.c._on_hotkeys_vrchat_only(False)
        self.hold(DEFAULT_GROW, 1.0)
        self.assertTrue(self.osc.sent)

    def test_stops_at_the_limit_never_past_it(self):
        self.make(hotkeys_enabled=True, hotkey_speed=10.0, hotkey_speed_unit="pct")
        self.connect()
        self.report(99.9)                                   # 99.9 m, limit 100 m
        self.hold(DEFAULT_GROW, 1.0)
        self.assertEqual(max(self.osc.sent), 10000.0)
        self.assertEqual(self.osc.sent[-1], 10000.0)
        self.assertIn("limit", self.window.status_msg.text())

    def test_both_keys_held_do_nothing(self):
        self.make(**self.HOTKEYS)
        self.connect()
        self.report(1.7)
        self.c.keys.down.add(DEFAULT_SHRINK)
        self.hold(DEFAULT_GROW, 1.0)
        self.assertEqual(self.osc.sent, [])

    def test_hold_stops_a_running_transition(self):
        self.make(transition_target_cm=200, transition_duration=10, transition_unit="s",
                  **self.HOTKEYS)
        self.connect()
        self.report(1.0)
        self.c._on_play()
        self.assertIsNotNone(self.c.transition)
        self.hold(DEFAULT_SHRINK, 0.5)
        self.assertIsNone(self.c.transition)
        self.assertLess(self.osc.sent[-1], 100.0)

    def test_setting_a_key_pauses_the_hotkeys(self):
        self.make(**self.HOTKEYS)
        self.connect()
        self.report(1.7)
        self.window.capturing_key = True
        self.hold(DEFAULT_GROW, 1.0)
        self.assertEqual(self.osc.sent, [])

    def test_disconnect_mid_hold_stops_it_for_good(self):
        self.make(**self.HOTKEYS)
        self.connect()
        self.report(1.7)
        self.hold(DEFAULT_GROW, 0.5)
        sent = len(self.osc.sent)
        self.assertGreater(sent, 0)
        self.osc.is_connected = False
        self.c._on_disconnected()
        self.connect()
        self.report(1.5)                                    # VRChat came back at 150 cm
        self.hold(DEFAULT_GROW, 0.5)                        # still the same press
        self.assertEqual(len(self.osc.sent), sent)
        self.release()
        self.hold(DEFAULT_GROW, 0.5)                        # a fresh press starts from 150
        self.assertAlmostEqual(self.osc.sent[-1], 150.0 * 1.05 ** 0.5, places=3)

    def test_avatar_change_mid_hold_keeps_going_without_a_burst(self):
        self.make(preserve_height_on_avatar_switch=True, **self.HOTKEYS)
        self.connect()
        self.report(1.7)
        self.hold(DEFAULT_GROW, 0.5)
        self.c._on_avatar_change("avtr_x", self.clock.t)
        self.assertFalse(self.c._burst_timer.isActive())
        before = len(self.osc.sent)
        self.hold(DEFAULT_GROW, 0.5)
        self.assertGreater(len(self.osc.sent), before)

    def test_setting_keys(self):
        self.make(**self.HOTKEYS)
        self.assertEqual(self.window.grow_key_btn.text(), "Num +")
        self.c._on_hotkey_captured("grow", 0x47, MOD_CTRL)
        self.assertEqual(self.c.hotkey_grow, Hotkey(0x47, MOD_CTRL))
        self.assertEqual(self.c.config.config["hotkey_grow"], {"vk": 0x47, "mods": MOD_CTRL})
        self.assertEqual(self.window.grow_key_btn.text(), "Ctrl + G")
        self.c._on_hotkey_captured("shrink", 0x47, MOD_CTRL)    # already the grow key
        self.assertEqual(self.c.hotkey_shrink, DEFAULT_SHRINK)
        self.assertIn("already", self.window.status_msg.text())

    def test_hotkey_settings_hidden_until_switched_on(self):
        self.make(hotkeys_enabled=False)
        self.assertTrue(self.window.hotkeys_details.isHidden())
        self.c._on_hotkeys_toggled(True)
        self.assertFalse(self.window.hotkeys_details.isHidden())
        self.assertTrue(self.c._hotkey_timer.isActive())

    # --- the in-VRChat menu ----------------------------------------------
    def test_menu_grow_works_with_hotkeys_off(self):
        self.make(hotkeys_enabled=False, hotkey_speed_unit="pct")   # keys off, 5 % / s
        self.connect()
        self.report(1.7)
        self.menu(MENU_GROW, True)
        self.assertTrue(self.c._hotkey_timer.isActive())
        self.ticks(2.0)
        sent = self.osc.sent
        self.assertGreaterEqual(len(sent), 19)
        self.assertEqual(sent, sorted(sent))
        self.assertAlmostEqual(sent[-1], 170.0 * 1.05 ** 2, places=1)
        self.assertEqual(self.window.activity_chip.text(), "growing (menu)")
        self.menu(MENU_GROW, False, dt=0.0)
        self.assertIn("Grew to", self.window.status_msg.text())
        self.assertIn("VRChat menu", self.window.status_msg.text())
        self.assertFalse(self.c._hotkey_timer.isActive())   # nothing left to watch
        n = len(self.osc.sent)
        self.ticks(1.0)
        self.assertEqual(len(self.osc.sent), n)

    def test_menu_shrink_waits_for_the_real_height(self):
        self.make()
        self.connect()
        self.menu(MENU_SHRINK, True)
        self.ticks(1.0)
        self.assertEqual(self.osc.sent, [])
        self.assertIn("waiting for VRChat", self.window.status_msg.text())

    def test_menu_saves_and_loads_slots(self):
        self.make()
        self.connect()
        self.report(1.7)
        self.tap(MENU_SAVE, 2)
        self.assertEqual(self.c.profiles["profile2"], 170.0)
        self.assertEqual(self.window.profile_load_btns[2].text(), "2 · 170 cm")
        self.report(1.2, dt=1.0)
        self.tap(MENU_LOAD, 2)
        self.assertEqual(self.osc.sent, [170.0])

    def test_menu_load_of_an_empty_slot_says_so(self):
        self.make()
        self.connect()
        self.report(1.7)
        self.tap(MENU_LOAD, 3)
        self.assertEqual(self.osc.sent, [])
        self.assertIn("empty", self.window.status_msg.text())

    def test_menu_play_pause_and_stop(self):
        self.make(transition_target_cm=200, transition_duration=10, transition_unit="s")
        self.connect()
        self.report(1.0)
        self.tap(MENU_PLAY)
        self.assertTrue(self.c.transition is not None and self.c.transition.playing)
        self.tap(MENU_PLAY)
        self.assertFalse(self.c.transition.playing)               # paused
        self.tap(MENU_PLAY)
        self.assertTrue(self.c.transition.playing)                # resumed
        self.tap(MENU_STOP)
        self.assertIsNone(self.c.transition)

    def test_menu_does_nothing_while_a_new_avatar_loads(self):
        self.make(transition_target_cm=200, transition_duration=10, transition_unit="s",
                  preserve_height_on_avatar_switch=False)
        self.connect()
        self.report(1.0)
        self.c._on_avatar_change("avtr_new", self.clock.t)
        self.menu(MENU_PLAY, True, dt=0.2)                         # VRChat loading the avatar
        self.assertIsNone(self.c.transition)

    def test_menu_held_through_an_avatar_change_is_let_go(self):
        self.make()
        self.connect()
        self.report(1.7)
        self.menu(MENU_GROW, True)
        self.ticks(0.5)
        self.c._on_avatar_change("avtr_x", self.clock.t)
        n = len(self.osc.sent)
        self.ticks(0.5)
        self.assertEqual(len(self.osc.sent), n)

    def test_menu_parameter_shows_the_avatar_has_it(self):
        self.make()
        self.connect()
        self.assertIn("Checking whether", self.window.menu_status.text())
        self.menu(MENU_GROW, False)
        self.assertIn("This avatar has the HeightShift menu", self.window.menu_status.text())
        self.c._on_menu_present(self.c._menu_round, False)        # an older answer
        self.assertIn("This avatar has the HeightShift menu", self.window.menu_status.text())
        self.osc.is_connected = False
        self.c._on_disconnected()
        self.assertEqual(self.window.menu_status.text(), "Waiting for VRChat.")

    # --- the size comparison ---------------------------------------------
    def test_comparison_shows_now_and_target(self):
        self.make(transition_target_cm=5000)
        self.assertEqual(self.window.ratio_value.text(), "")      # nothing read yet
        self.connect()
        self.report(1.7)
        self.assertEqual(self.window.target_spin.text(), "50 m")
        self.assertEqual(self.window._ratio, ("×29.4", "bigger"))
        self.assertTrue(self.window.ratio_value.text().startswith("×29.4"))
        self.assertIn("bigger", self.window.ratio_value.text())
        self.assertEqual(self.window.figure.shown_cm(), (170.0, 5000.0))
        self.assertIn("even", self.window.target_note.text())

    def test_the_scale_only_picks_the_target(self):
        """Picking on the scale never sends: Go instant or Go timed does."""
        self.make(transition_target_cm=5000, profiles={"profile1": 250.0})
        self.connect()
        self.report(1.7)
        fig = self.window.figure
        fig.target_previewed.emit(800.0)                         # the pointer, dragged
        self.assertEqual(self.c.config.config["transition_target_cm"], 5000)   # not yet saved
        fig.target_committed.emit(800.0)                         # … and let go
        self.assertEqual(self.c.config.config["transition_target_cm"], 800.0)
        self.assertEqual(self.window.target_spin.text(), "800 cm")
        # the ring at your height, dragged onto saved height 1 and let go
        ring = QPoint(round(fig.axis_x()), round(fig.y_of(170.0)))
        mark = QPoint(ring.x(), round(fig.y_of(250.0)) + 2)      # snaps onto it
        QTest.mousePress(fig, Qt.LeftButton, Qt.NoModifier, ring)
        QTest.mouseMove(fig, mark)
        QTest.mouseRelease(fig, Qt.LeftButton, Qt.NoModifier, mark)
        self.assertEqual(self.window.target_spin.value(), 250.0)
        self.assertEqual(self.c.height_cm, 170.0)
        self.assertEqual(self.osc.sent, [])                      # nothing sent
        self.window.go_instant_btn.click()                       # now it goes
        self.assertEqual(self.osc.sent, [250.0])

    def test_the_figure_shrinks_before_the_height_panel_wraps(self):
        from ui.figure import FIT_MIN
        self.make(settings_open=False)
        w = self.window
        w.setAttribute(Qt.WA_DontShowOnScreen, True)
        w.show()
        for _ in range(3):
            _app.processEvents()
        fig = w.figure
        side = (w._figure_chrome() + w.top_row.spacing()
                + w.height_panel.minimumSizeHint().width())     # all but the figure
        # the decision, for a work column `room` px wide
        self.assertEqual(w._top_row_plan(side + fig.stage_size(1.0)[0] + 40, True), (True, 1.0))
        beside, fit = w._top_row_plan(side + fig.stage_size(0.8)[0], True)
        self.assertTrue(beside)
        self.assertAlmostEqual(fit, 0.8, delta=0.01)             # shrunk, still beside
        smallest = side + fig.stage_size(FIT_MIN)[0]
        self.assertTrue(w._top_row_plan(smallest, True)[0])
        self.assertEqual(w._top_row_plan(smallest - 1, True)[0], False)   # now it wraps …
        self.assertEqual(w._top_row_plan(smallest + 8, False)[0], False)  # … and stays
        self.assertTrue(w._top_row_plan(smallest + 20, False)[0])         # until there's room
        self.assertEqual(w._top_row_plan(fig.stage_size(1.0)[0] + 100, False), (False, 1.0))
        # and the window follows it as it is resized
        bar = w.work_scroll.verticalScrollBar().sizeHint().width()
        for width, fit in ((side + fig.stage_size(1.0)[0] + bar + 24 + 40, 1.0),
                           (side + fig.stage_size(0.8)[0] + bar + 24, 0.8)):
            w.resize(width, 800)
            for _ in range(4):
                _app.processEvents()
            if w.width() != width:
                continue                    # narrower than the window may be here
            self.assertEqual(w.top_row.direction(), QBoxLayout.LeftToRight)
            self.assertAlmostEqual(fig.fit, fit, delta=0.01, msg=width)
        w.close()

    def test_the_scale_follows_the_window_state(self):
        self.make(profiles={"profile1": 30.0})
        fig = self.window.figure
        self.assertTrue(fig._mark_ok[1][0])        # picking a target needs no VRChat
        self.assertFalse(fig._target_locked)
        self.connect()
        self.report(1.7)
        self.assertTrue(fig._mark_ok[1][0])
        self.assertEqual(fig._saved[1], 30.0)
        self.c._on_slider_range(10.0, 5000.0)
        self.assertEqual((fig._lo, fig._hi), (10.0, 5000.0))

    def test_a_range_typed_on_the_scale_is_kept_or_refused(self):
        self.make()
        self.window.figure.range_committed.emit(10.0, 5000.0)
        self.assertEqual((self.c.slider_lo, self.c.slider_hi), (10.0, 5000.0))
        self.assertEqual(self.c.config.config["slider_max_value"], 5000.0)
        self.assertEqual(self.window.range_max_spin.value(), 5000.0)   # Settings follows
        self.window.figure.range_committed.emit(10.0, 50_000.0)  # above the 100 m limit
        self.assertEqual(self.c.slider_hi, 5000.0)               # refused, not clamped
        self.assertIn("limit", self.window.status_msg.text())

    def test_updates_per_second(self):
        self.make()
        self.assertEqual(self.c._tick_timer.interval(), 33)       # 30 a second by default
        self.assertEqual(self.c._hotkey_timer.interval(), 33)
        self.window.send_rate_seg._buttons["60"].click()
        self.assertEqual(self.c._tick_timer.interval(), 17)
        self.assertEqual(self.c._hotkey_timer.interval(), 17)
        self.assertEqual(self.c.config.config["send_rate"], 60)
        self.c._on_send_rate(1000)                               # not one of the choices
        self.assertEqual(self.c.send_rate, 60)

    def test_updates_per_second_is_remembered(self):
        self.make(send_rate=10)
        self.assertEqual(self.c._tick_timer.interval(), 100)
        self.assertEqual(self.window.send_rate_seg.value(), "10")

    # --- pick a target, then go instant or go timed ----------------------
    def test_a_saved_height_is_loaded_as_the_target_not_sent(self):
        self.make(profiles={"profile2": 5000.0}, transition_target_cm=200)
        self.connect()
        self.report(1.7)
        self.window.profile_load_btns[2].click()
        self.assertEqual(self.osc.sent, [])                      # nothing sent
        self.assertEqual(self.window.target_spin.value(), 5000.0)
        self.assertEqual(self.c.config.config["transition_target_cm"], 5000.0)
        self.assertTrue(self.window.profile_load_btns[2].isChecked())   # it is the target

    # --- what a click does: saved heights and the scale --------------------
    def test_six_saved_heights(self):
        self.make()
        self.assertEqual(sorted(self.window.profile_load_btns), [1, 2, 3, 4, 5, 6])
        self.assertEqual(sorted(self.window.profile_save_btns), [1, 2, 3, 4, 5, 6])
        self.connect()
        self.report(0.03)
        self.window.profile_save_btns[6].click()
        self.assertEqual(self.c.profiles["profile6"], 3.0)

    def test_a_select_slot_only_picks_the_target(self):
        self.make(profiles={"profile1": 140.0})
        self.connect()
        self.report(1.7)
        self.window.profile_load_btns[1].click()
        self.assertEqual(self.window.target_spin.value(), 140.0)
        self.assertEqual(self.osc.sent, [])
        self.assertIsNone(self.c.transition)

    def test_an_instant_slot_goes_there_at_once(self):
        # "I really liked how easy I could instantly go down to 1 cm"
        self.make(profiles={"profile2": 1.0}, profile_actions={"profile2": "instant"})
        self.connect()
        self.report(1.7)
        self.assertEqual(self.window.profile_load_btns[2].property("kind"), "instant")
        self.window.profile_load_btns[2].click()
        self.assertEqual(self.osc.sent, [1.0])
        self.assertIsNone(self.c.transition)

    def test_a_timed_slot_starts_the_transition(self):
        self.make(profiles={"profile3": 300.0}, profile_actions={"profile3": "timed"})
        self.connect()
        self.report(1.7)
        self.window.profile_load_btns[3].click()
        self.assertIsNotNone(self.c.transition)
        self.assertTrue(self.c.transition.playing)
        self.assertEqual(self.window.target_spin.value(), 300.0)

    def test_an_empty_slot_takes_a_right_click_but_not_a_click(self):
        self.make()
        self.connect()
        self.report(1.7)
        btn = self.window.profile_load_btns[4]                       # empty
        self.assertTrue(btn.isEnabled())                             # right-click reaches it
        self.assertEqual(btn.property("usable"), "false")
        self.assertEqual(btn.contextMenuPolicy(), Qt.CustomContextMenu)
        target = self.window.target_spin.value()
        btn.click()                                                  # a click does nothing
        self.assertEqual(self.window.target_spin.value(), target)
        self.assertFalse(btn.isChecked())
        self.assertEqual(self.osc.sent, [])
        self.window.slot_action_changed.emit(4, "instant")           # what its menu does
        self.assertEqual(btn.property("kind"), "instant")
        self.window.profile_save_btns[4].click()                     # save 1.7 m into it
        self.assertEqual(btn.property("usable"), "true")
        self.c._on_adjust(10.0)                                      # now 180 cm
        btn.click()                                                  # instant: back to 170
        self.assertEqual(self.osc.sent[-1], 170.0)

    def test_a_slots_action_is_set_saved_and_shown(self):
        self.make(profiles={"profile1": 140.0})
        self.window.slot_action_segs[1].changed.emit("instant")    # Settings
        self.assertEqual(self.c.slot_actions[1], "instant")
        self.assertEqual(self.c.config.config["profile_actions"]["profile1"], "instant")
        self.assertEqual(self.window.profile_load_btns[1].property("kind"), "instant")
        self.window.slot_action_changed.emit(1, "timed")             # right-click menu
        self.assertEqual(self.window.slot_action_segs[1].value(), "timed")
        self.window.slot_action_changed.emit(1, "nonsense")          # ignored
        self.assertEqual(self.c.slot_actions[1], "timed")

    def test_the_scale_mode_decides_what_a_pick_does(self):
        self.make(transition_target_cm=170)
        self.connect()
        self.report(1.7)
        fig, switch = self.window.figure, self.window.mode_switch
        fig.target_committed.emit(500.0)                             # select: picks only
        self.assertEqual(self.osc.sent, [])
        switch.current.click()                                       # unfolds inside the card
        self.assertTrue(switch.expanded)
        switch._option_btns["instant"].click()
        self.assertFalse(switch.expanded)
        self.assertEqual(self.c.config.config["scale_mode"], "instant")
        fig.target_committed.emit(2.0)                               # instant: there at once
        self.assertEqual(self.osc.sent, [2.0])
        self.c._on_scale_mode("timed")
        self.assertEqual(switch.mode, "timed")
        fig.target_committed.emit(800.0)                             # timed: the transition
        self.assertTrue(self.c.transition is not None and self.c.transition.playing)

    def test_go_instant_sends_the_target_at_once(self):
        self.make(transition_target_cm=5000)
        self.connect()
        self.report(1.7)
        self.window.go_instant_btn.click()
        self.assertEqual(self.osc.sent, [5000.0])
        self.assertIsNone(self.c.transition)
        self.assertFalse(self.window.go_instant_btn.isEnabled())      # there now

    def test_go_instant_waits_for_vrchat_and_skips_a_no_op(self):
        self.make(transition_target_cm=170)
        self.assertFalse(self.window.go_instant_btn.isEnabled())      # not connected
        self.c._on_go_instant()
        self.assertEqual(self.osc.sent, [])
        self.connect()
        self.report(1.7)
        self.assertFalse(self.window.go_instant_btn.isEnabled())      # already there
        self.assertIn("Already", self.window.go_instant_btn.toolTip())

    def test_go_timed_is_the_transition(self):
        self.make(transition_target_cm=200, transition_duration=10, transition_unit="s")
        self.connect()
        self.report(1.0)
        self.window.play_btn.click()
        self.assertTrue(self.c.transition.playing)
        self.assertTrue(self.window.go_instant_btn.isHidden())        # Stop | Pause now
        self.assertFalse(self.window.stop_btn.isHidden())
        self.assertEqual(self.window.profile_load_btns[1].property("usable"), "false")  # fixed

    def test_a_typed_target_reads_like_a_height(self):
        self.make(transition_target_cm=200)
        spin = self.window.target_spin
        spin.lineEdit().setText("50 m")
        spin.interpretText()
        self.assertEqual(spin.value(), 5000.0)
        self.assertEqual(self.c.config.config["transition_target_cm"], 5000.0)
        self.assertEqual(spin.text(), "50 m")

    # --- startup ------------------------------------------------------
    def test_query_mode_never_writes_on_startup(self):
        self.make()
        self.connect()
        self.report(1.734)
        self.assertEqual(self.osc.sent, [])
        self.assertAlmostEqual(self.c.height_cm, 173.4)    # exact, not rounded

    def test_reported_height_is_not_clamped(self):
        self.make()
        self.connect()
        self.report(250.0)                                 # 250 m, lock on
        self.assertAlmostEqual(self.c.height_cm, 25000.0)
        self.assertEqual(self.osc.sent, [])

    def test_fixed_mode_writes_once_per_run_even_if_vrchat_is_late(self):
        self.make(startup_mode="fixed_height", startup_height=150)
        self.clock.t += 60                                 # VRChat starts a minute later
        self.connect()
        self.assertEqual(self.osc.sent, [150.0])
        self.osc.is_connected = False
        self.c._on_disconnected()
        self.connect()
        self.assertEqual(self.osc.sent, [150.0])           # not again on reconnect

    # --- relative steps need a known base ------------------------------
    def test_steps_do_nothing_until_height_is_known(self):
        self.make()
        self.connect()
        self.c._on_adjust(1.0)
        self.assertEqual(self.osc.sent, [])
        self.assertFalse(self.window.step_btns[0].isEnabled())

    def test_step_uses_exact_base(self):
        self.make()
        self.connect()
        self.report(1.734)
        self.c._on_adjust(1.0)
        self.assertEqual(self.osc.sent, [174.4])

    def test_rapid_steps_are_not_pulled_back_by_echoes(self):
        self.make()
        self.connect()
        self.report(1.70)
        self.c._on_adjust(1.0)            # 171
        self.report(1.70, dt=0.0)         # stale report stamped at the same instant: dropped
        self.report(1.71, dt=0.05)        # echo of 171, held
        self.c._on_adjust(1.0)            # must be 172, not 172 from a stale base
        self.c._on_adjust(1.0)            # 173
        self.assertEqual(self.osc.sent, [171.0, 172.0, 173.0])

    def test_slow_read_cannot_undo_a_height_just_set(self):
        # Height unknown, an HTTP read is on its way (asked at t0); meanwhile
        # profile 1 sets 167 cm and VRChat's echo arrives. The read then answers
        # with the old 129.9 cm: it was asked for before the send, so it loses.
        self.make(profiles={"profile1": 167})
        self.connect()
        asked_at = self.clock.t
        self.clock.t += 0.2
        self.c._on_profile_load(1)
        self.report(1.67, dt=0.05)                         # the echo
        self.clock.t += 0.3
        self.c._on_reported(1.299, asked_at)               # the slow read lands
        self.advance(2.0)
        self.assertAlmostEqual(self.c.height_cm, 167.0)
        self.c._on_adjust(1.0)
        self.assertEqual(self.osc.sent, [167.0, 168.0])

    def test_read_from_before_an_avatar_change_is_not_the_new_height(self):
        self.make(preserve_height_on_avatar_switch=False)
        self.connect()
        self.report(1.5)
        asked_at = self.clock.t + 1                        # read asked for, old avatar
        self.c._on_avatar_change("avtr_x", self.clock.t + 1.1)
        self.clock.t += 1.3
        self.c._on_reported(1.5, asked_at)                 # answer about the old avatar
        self.assertIsNone(self.c.height_cm)
        self.report(1.2, dt=0.1)                           # the new avatar's own report
        self.assertAlmostEqual(self.c.height_cm, 120.0)

    def test_read_result_goes_through_the_read_path(self):
        self.make()
        self.connect()
        self.osc.read_result = (1.29905224, self.clock.t)
        seen = []
        self.c._sig_height.connect(lambda m, t: seen.append((m, t)))
        self.c._query_round = 7
        self.c._query_height(7)
        for _ in range(100):                               # the read runs on a thread
            _app.processEvents()
            if seen:
                break
            time.sleep(0.01)
        _app.processEvents()
        self.assertEqual(seen, [(1.29905224, 1000.0)])     # stamped when asked
        self.assertAlmostEqual(self.c.height_cm, 129.905224)
        self.assertEqual(self.osc.sent, [])

    def test_an_older_read_round_stops(self):
        self.make()
        self.connect()
        self.c._query_round = 3
        self.c._query_height(2)                            # a timer from an older round
        self.assertEqual(self.c._query_attempts, 0)
        self.c._on_query_missed(2, 1)
        self.assertEqual(self.c._query_attempts, 0)
        self.c._query_height(3)
        self.assertEqual(self.c._query_attempts, 1)
        self.osc.is_connected = False                      # let the read's miss end quietly
        time.sleep(0.05)
        _app.processEvents()

    def test_disconnect_forgets_the_height(self):
        self.make()
        self.connect()
        self.report(1.5)
        self.osc.is_connected = False
        self.c._on_disconnected()
        self.assertIsNone(self.c.height_cm)
        self.osc.is_connected = True
        self.c._on_adjust(1.0)
        self.assertEqual(self.osc.sent, [])

    # --- limits ---------------------------------------------------------
    def test_a_nudge_stops_at_the_top(self):
        self.make()
        self.connect()
        self.report(99.995)
        self.c._on_adjust(100.0)
        self.assertEqual(self.osc.sent, [10000.0])               # the 100 m limit
        self.assertIn("stopped at the highest", self.window.status_msg.text())

    def test_minus_100_at_85_cm_goes_to_1_cm(self):
        # as 1.x did: "I could instantly go down to 1 cm when someone was
        # about to step on me"
        self.make()
        self.connect()
        self.report(0.85)
        self.c._on_adjust(-100.0)
        self.assertEqual(self.osc.sent, [1.0])

    def test_minus_1_at_2_cm_reaches_1_cm(self):
        # VRChat's 32-bit float for 2 cm is 1.99999995 cm: -1 is still 1 cm
        two_cm = struct.unpack("f", struct.pack("f", 0.02))[0]
        self.make()
        self.connect()
        self.report(two_cm)
        self.c._on_adjust(-1.0)
        self.assertEqual(self.osc.sent, [1.0])

    def test_go_timed_from_1_cm(self):
        # VRChat's 1 cm reads as 0.99999998 cm: it is still 1 cm, not "below
        # the 1 cm minimum", so the transition can start from it
        one_cm = struct.unpack("f", struct.pack("f", 0.01))[0]
        self.make(transition_target_cm=119, transition_duration=5, transition_unit="s")
        self.connect()
        self.report(one_cm)
        self.assertTrue(self.window.play_btn.isEnabled())
        self.window.play_btn.click()
        self.assertTrue(self.c.transition is not None and self.c.transition.playing)

    def test_at_1_cm_a_nudge_down_says_so(self):
        one_cm = struct.unpack("f", struct.pack("f", 0.01))[0]
        self.make()
        self.connect()
        self.report(one_cm)
        self.c._on_adjust(-10.0)
        self.assertEqual(self.osc.sent, [])
        self.assertIn("Already at the lowest", self.window.status_msg.text())

    def test_profile_above_limit_is_refused(self):
        self.make(profiles={"profile1": 50_000})
        self.connect()
        self.report(1.7)
        self.c._on_profile_load(1)
        self.assertEqual(self.osc.sent, [])
        self.assertEqual(self.window.profile_load_btns[1].property("usable"), "false")

    def test_corrupt_profile_values_are_ignored(self):
        self.make(profiles={"profile1": "abc", "profile2": None, "profile3": -5,
                            "profile4": 180})
        self.assertEqual(self.c.profiles, {"profile4": 180.0})

    # --- preserve across avatar change ----------------------------------
    def test_preserve_sends_the_height_from_before_the_change(self):
        self.make(preserve_height_on_avatar_switch=True)
        self.connect()
        self.report(1.5)
        self.clock.t += 10
        self.c._on_reported(1.2, self.clock.t - 0.05)      # new avatar default, stamped just before
        self.c._on_avatar_change("avtr_x", self.clock.t)
        self.c._burst_timer.stop()
        self.assertTrue(self.osc.sent)
        self.assertTrue(all(v == 150.0 for v in self.osc.sent))

    def test_duplicate_avatar_change_keeps_the_same_target(self):
        # Seen in the real log: /avatar/change arrives twice (VRChat + router 518).
        self.make(preserve_height_on_avatar_switch=True)
        self.connect()
        self.report(1.2990522)
        self.clock.t += 10
        t_change = self.clock.t
        self.c._on_avatar_change("avtr_x", t_change)
        self.clock.t += 0.01
        self.c._on_reported(5.0, self.clock.t)             # new avatar's default arrives
        self.c._on_avatar_change("avtr_x", t_change + 0.001)
        self.c._burst_timer.stop()
        self.assertTrue(self.osc.sent)
        self.assertTrue(all(abs(v - 129.90522) < 1e-3 for v in self.osc.sent), self.osc.sent)

    def test_no_preserve_burst_when_height_was_never_known(self):
        self.make(preserve_height_on_avatar_switch=True)
        self.connect()
        self.c._on_avatar_change("avtr_x", self.clock.t)
        self.assertEqual(self.osc.sent, [])

    def test_user_click_cancels_the_burst(self):
        self.make(preserve_height_on_avatar_switch=True)
        self.connect()
        self.report(1.5)
        self.clock.t += 5
        self.c._on_avatar_change("avtr_x", self.clock.t)
        self.c._on_adjust(10.0)
        self.assertFalse(self.c._burst_timer.isActive())
        self.assertEqual(self.osc.sent[-1], 160.0)

    def test_preserve_off_reads_the_new_height(self):
        self.make(preserve_height_on_avatar_switch=False)
        self.connect()
        self.report(1.5)
        self.c._on_avatar_change("avtr_x", self.clock.t + 1)
        self.assertEqual(self.osc.sent, [])
        self.assertIsNone(self.c.height_cm)

    # --- slow transition ------------------------------------------------
    def test_transition_reaches_the_end_on_time(self):
        self.make(transition_target_cm=200, transition_duration=10, transition_unit="s")
        self.connect()
        self.report(1.0)
        self.c._on_play()
        self.assertIsNotNone(self.c.transition)
        for _ in range(110):
            self.clock.t += 0.1
            self.c._transition_tick()
        self.assertIsNone(self.c.transition)
        self.assertEqual(self.osc.sent[-1], 200.0)
        self.assertEqual(self.osc.sent, sorted(self.osc.sent))   # only ever grows
        self.assertTrue(all(100 <= v <= 200 for v in self.osc.sent))

    def test_transition_waits_for_known_height(self):
        self.make(transition_target_cm=200, transition_duration=10, transition_unit="s")
        self.connect()
        self.c._on_play()
        self.assertIsNone(self.c.transition)
        self.assertEqual(self.osc.sent, [])

    def test_manual_change_stops_the_transition(self):
        self.make(transition_target_cm=300, transition_duration=10, transition_unit="s")
        self.connect()
        self.report(1.0)
        self.c._on_play()
        self.clock.t += 2
        self.c._transition_tick()
        self.c._on_adjust(-10.0)
        self.assertIsNone(self.c.transition)

    def test_unlocking_stretches_the_scale_to_1000_m_and_back(self):
        self.make()
        self.assertEqual(self.c.slider_hi, 10_000.0)               # 100 m, the limit
        self.c._on_unlock(True)
        self.assertEqual(self.c.slider_hi, 100_000.0)              # 1000 m: the new limit
        self.assertEqual(self.window.figure._hi, 100_000.0)
        self.c._on_unlock(False)
        self.assertEqual(self.c.slider_hi, 10_000.0)
        # a range narrowed by hand stays as it is
        self.c._on_slider_range(100.0, 300.0)
        self.c._on_unlock(True)
        self.assertEqual((self.c.slider_lo, self.c.slider_hi), (100.0, 300.0))

    def test_locking_mid_transition_stops_it(self):
        self.make(unlock_upper_limit=True, transition_target_cm=20_000,
                  transition_duration=10, transition_unit="s")
        self.connect()
        self.report(95.0)
        self.c._on_play()
        self.window.unlock_cb.setChecked(False)
        self.clock.t += 5
        self.c._transition_tick()
        self.assertIsNone(self.c.transition)
        self.assertTrue(all(v <= 10_000 for v in self.osc.sent))

    def test_pause_and_resume_keep_the_curve(self):
        self.make(transition_target_cm=200, transition_duration=10, transition_unit="s")
        self.connect()
        self.report(1.0)
        self.c._on_play()
        self.clock.t += 4
        self.c._transition_tick()
        self.c._on_pause()
        self.clock.t += 100
        self.c._on_play()                                   # resume
        self.assertAlmostEqual(self.osc.sent[-1], 140.0, places=3)


if __name__ == "__main__":
    unittest.main()
