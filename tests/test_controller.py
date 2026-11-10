"""Controller behaviour with a fake OSC manager: what does (and does not) get
written to VRChat. Runs Qt offscreen; no network, no VRChat."""

import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import controller  # noqa: E402
from config_manager import ConfigManager  # noqa: E402
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


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self._orig = (controller.VRChatOSCManager, controller.Router518KeepAlive,
                      controller.now)
        controller.VRChatOSCManager = FakeOSC
        controller.Router518KeepAlive = FakeRouter
        self.clock = Clock()
        controller.now = self.clock
        self.tmp = tempfile.mkdtemp(prefix="hs-ctrl-")
        self.cfg_path = os.path.join(self.tmp, "c.json")

    def tearDown(self):
        (controller.VRChatOSCManager, controller.Router518KeepAlive,
         controller.now) = self._orig
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
    def test_above_limit_is_refused_not_clamped(self):
        self.make()
        self.connect()
        self.report(99.995)
        self.c._on_adjust(100.0)
        self.assertEqual(self.osc.sent, [])
        self.window.unlock_cb.setChecked(True)
        self.c._on_adjust(100.0)
        self.assertEqual(self.osc.sent, [10099.5])

    def test_profile_above_limit_is_refused(self):
        self.make(profiles={"profile1": 50_000})
        self.connect()
        self.report(1.7)
        self.c._on_profile_load(1)
        self.assertEqual(self.osc.sent, [])
        self.assertFalse(self.window.profile_load_btns[1].isEnabled())

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
