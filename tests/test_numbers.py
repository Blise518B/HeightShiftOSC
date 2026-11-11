"""Heights as VRChat really sends them, through everything that compares,
rounds, formats or checks a height.

OSC carries the eye height in metres as a 32-bit float, so a height never
arrives exact: 1 cm is 0.99999998 cm, 2 cm is 1.99999995 cm, 1.7 m is
170.00000477 cm. Every path must treat that as the height it stands for —
at the limits, at the unit boundaries (cm / m / km) and in between.
(Found by users: −1 at "2 cm" was refused, Go timed at "1 cm" too.)
Runs Qt offscreen."""

import os
import struct
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from constants import MAX_HEIGHT_CM, MIN_HEIGHT_CM, UNLOCKED_MAX_HEIGHT_CM  # noqa: E402
from height_logic import (  # noqa: E402
    CURVE_LINEAR,
    CURVE_SCALE,
    SPEED_CM,
    SPEED_PERCENT,
    Transition,
    check_write,
    format_height,
    format_height_alt,
    hold_height,
    parse_height,
    same_height,
    scale_fraction,
    scale_height,
)
from tests import test_controller as _tc  # noqa: E402  (its fakes and fixture, not its tests)


def f32_m(cm: float) -> float:
    """What VRChat sends for `cm`: metres as a 32-bit float."""
    return struct.unpack("f", struct.pack("f", cm / 100.0))[0]


def f32(cm: float) -> float:
    """…and what it reads as, back in cm."""
    return f32_m(cm) * 100.0


# at and near the limits, the unit boundaries, and ordinary heights
HEIGHTS = (1, 1.1, 1.5, 2, 3, 9.9, 10, 33.3, 99.9, 100, 119, 140, 170, 173.4, 500,
           999.9, 1000, 1234.5, 5000, 9999.9, 10_000)
UNLOCKED = (10_000.1, 12_345, 50_000, 99_999.9, 100_000)
# the window sweeps build one window per case: the limits, the unit edges and
# a few ordinary heights (the logic sweeps above take every height)
WINDOW_HEIGHTS = (1, 2, 3, 99.9, 170, 999.9, 1000, 9999.9, 10_000)


class LogicTest(unittest.TestCase):
    def test_vrchats_heights_pass_the_write_check(self):
        for cm in HEIGHTS:
            with self.subTest(cm=cm):
                self.assertIsNone(check_write(f32(cm), False))
        for cm in UNLOCKED:
            with self.subTest(cm=cm):
                self.assertIsNone(check_write(f32(cm), True))
                self.assertIsNotNone(check_write(f32(cm), False))   # locked: too tall

    def test_real_overshoots_are_still_refused(self):
        self.assertIsNotNone(check_write(0.999, False))           # 0.1 mm short
        self.assertIsNotNone(check_write(MAX_HEIGHT_CM + 0.1, False))
        self.assertIsNotNone(check_write(UNLOCKED_MAX_HEIGHT_CM + 1, True))

    def test_they_read_and_save_as_the_height_they_are(self):
        for cm in HEIGHTS + UNLOCKED:
            with self.subTest(cm=cm):
                self.assertEqual(format_height(f32(cm)), format_height(cm))
                self.assertTrue(same_height(f32(cm), cm))
                self.assertEqual(round(f32(cm), 1), round(cm, 1))      # a saved height

    def test_the_unit_follows_the_rounded_value(self):
        # 999.96 cm shows as "10 m", never as "1,000 cm"; the same at 1 km
        self.assertEqual(format_height(999.94), "999.9 cm")
        self.assertEqual(format_height(999.96), "10 m")
        self.assertEqual(format_height(99_999.4), "999.994 m")
        self.assertEqual(format_height(1234.5), "12.345 m")
        self.assertEqual(format_height(1250), "12.5 m")
        self.assertEqual(format_height(99_999.6), "999.996 m")
        self.assertEqual(format_height(99_999.96), "1 km")
        self.assertEqual(format_height(f32(1)), "1 cm")
        self.assertEqual(format_height(f32(2)), "2 cm")

    def test_the_line_under_shows_the_other_unit(self):
        for cm in HEIGHTS + UNLOCKED + (99.96, 999.94, 999.96, 99_999.4, 99_999.96):
            for value in (cm, f32(cm)):
                with self.subTest(value=value):
                    main, alt = format_height(value), format_height_alt(value)
                    self.assertNotEqual(main.split()[-1], alt.split()[-1])
                    # (display only: its thousands separators are not a decimal comma)
                    self.assertTrue(same_height(parse_height(alt.replace(",", "")), parse_height(main),
                                                tolerance_cm=0.05 if value < 99_999.95 else 50))

    def test_typed_back_what_is_shown(self):
        for cm in HEIGHTS + UNLOCKED:
            with self.subTest(cm=cm):
                back = parse_height(format_height(cm))
                self.assertIsNotNone(back)
                tolerance = 0.05 if cm < 99_999.95 else 50.0          # km shows whole metres
                self.assertTrue(same_height(back, cm, tolerance_cm=tolerance))

    def test_a_transition_ends_exactly_and_stays_between_its_ends(self):
        for start in (f32(1), f32(2), f32(170), f32(10_000)):
            for end in (1.0, 119.0, 10_000.0):
                for curve in (CURVE_LINEAR, CURVE_SCALE):
                    with self.subTest(start=start, end=end, curve=curve):
                        t = Transition(start, end, 5.0, curve)
                        self.assertEqual(t.value_at(1.0), end)
                        lo, hi = min(start, end), max(start, end)
                        for i in range(101):
                            v = t.value_at(i / 100)
                            self.assertTrue(lo - 1e-9 <= v <= hi + 1e-9)
                            self.assertIsNone(check_write(v, False))

    def test_holding_from_the_limits(self):
        # the caller clamps; nothing here may produce a non-number or a jump
        for base in (f32(1), f32(10_000)):
            for unit, speed in ((SPEED_CM, 5.0), (SPEED_PERCENT, 5.0)):
                for direction in (1, -1):
                    v = hold_height(base, 0.1, speed, unit, direction)
                    self.assertTrue(abs(v - base) < 0.6 + base * 0.01)

    def test_the_scale_at_its_ends(self):
        self.assertEqual(scale_height(0.0, 1, 10_000), 1.0)
        self.assertEqual(scale_height(1.0, 1, 10_000), 10_000.0)
        for cm in (f32(1), f32(10_000)):
            self.assertTrue(0.0 <= scale_fraction(cm, 1, 10_000) <= 1.0)


class ControllerNumbersTest(_tc.ControllerTest):
    """The window's actions from heights as VRChat sends them."""

    def at(self, cm, **config):
        self.make(**config)
        self.connect()
        self.report(f32_m(cm))
        return self.c

    def test_nudges_from_every_height(self):
        for cm in WINDOW_HEIGHTS:
            for delta in (1, -1, 10, -10, 100, -100):
                with self.subTest(cm=cm, delta=delta):
                    self.at(cm)
                    self.c._on_adjust(float(delta))
                    want = min(MAX_HEIGHT_CM, max(MIN_HEIGHT_CM, round(cm + delta, 4)))
                    if abs(want - cm) < 0.01:                      # already at a limit
                        self.assertEqual(self.osc.sent, [])
                    else:
                        self.assertEqual(len(self.osc.sent), 1)
                        self.assertAlmostEqual(self.osc.sent[0], want, places=3)
                        self.assertIsNone(check_write(self.osc.sent[0], False))
                    self.tearDown(); self.setUp()

    def test_go_instant_and_go_timed_from_every_height(self):
        for cm in WINDOW_HEIGHTS:
            for target in (1.0, 119.0, 10_000.0):
                with self.subTest(cm=cm, target=target):
                    self.at(cm, transition_target_cm=target, transition_duration=5,
                            transition_unit="s")
                    there = same_height(cm, target)
                    self.assertEqual(self.window.go_instant_btn.isEnabled(), not there)
                    self.assertEqual(self.window.play_btn.isEnabled(), not there,
                                     self.window.transition_status.text())
                    self.window.go_instant_btn.click()
                    self.assertEqual(self.osc.sent, [] if there else [target])
                    self.tearDown(); self.setUp()

    def test_saving_from_every_height_keeps_what_is_shown(self):
        for cm in WINDOW_HEIGHTS:
            with self.subTest(cm=cm):
                self.at(cm)
                self.window.profile_save_btns[5].click()
                saved = self.c.profiles["profile5"]
                self.assertEqual(saved, round(cm, 1))
                self.assertEqual(format_height(saved), format_height(cm))
                self.tearDown(); self.setUp()

    def test_an_instant_slot_at_its_own_height_sends_nothing(self):
        self.at(1, profiles={"profile1": 1.0}, profile_actions={"profile1": "instant"})
        self.window.profile_load_btns[1].click()
        self.assertEqual(self.osc.sent, [])
        self.assertIn("Already", self.window.status_msg.text())

    def test_holding_stops_at_the_limits(self):
        for cm, key in ((1, _tc.DEFAULT_SHRINK), (10_000, _tc.DEFAULT_GROW)):
            with self.subTest(cm=cm):
                self.at(cm, hotkeys_enabled=True, hotkey_speed=5.0, hotkey_speed_unit="cm")
                self.hold(key, 1.0)
                for v in self.osc.sent:
                    self.assertIsNone(check_write(v, False))
                self.release()
                self.tearDown(); self.setUp()


# the inherited ControllerTest tests run in test_controller.py already
for _name in [n for n in dir(_tc.ControllerTest) if n.startswith("test_")]:
    setattr(ControllerNumbersTest, _name, None)


if __name__ == "__main__":
    unittest.main()
