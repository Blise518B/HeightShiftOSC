import math
import unittest

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

from constants import (
    MAX_HEIGHT_CM,
    MENU_GROW,
    MENU_LOAD,
    MENU_PLAY,
    MENU_SAVE,
    MENU_SHRINK,
    MENU_STOP,
    MIN_HEIGHT_CM,
    UNLOCKED_MAX_HEIGHT_CM,
)
from height_logic import (
    CURVE_LINEAR,
    CURVE_SCALE,
    SPEED_CM,
    SPEED_PERCENT,
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
    parse_height,
    interpolate,
    reported_cm,
    scale_decades,
    scale_fraction,
    scale_height,
    tidy_height,
)


class TestCheckWrite(unittest.TestCase):
    def test_accepts_the_range(self):
        self.assertIsNone(check_write(MIN_HEIGHT_CM, False))
        self.assertIsNone(check_write(170.4, False))
        self.assertIsNone(check_write(MAX_HEIGHT_CM, False))

    def test_refuses_instead_of_clamping(self):
        self.assertIn("limit", check_write(MAX_HEIGHT_CM + 0.1, False))
        self.assertIn("minimum", check_write(0.5, False))
        # VRChat's 32-bit 1 cm (0.99999998 cm) is 1 cm, a real 0.999 cm is not
        self.assertIsNone(check_write(0.009999999776482582 * 100, False))
        self.assertIn("minimum", check_write(0.999, False))
        self.assertIsNone(check_write(MAX_HEIGHT_CM * (1 + 1e-7), False))
        self.assertIsNotNone(check_write(0, False))
        self.assertIsNotNone(check_write(-5, True))

    def test_unlock_raises_the_ceiling_only(self):
        self.assertIsNone(check_write(50_000, True))
        self.assertIsNone(check_write(UNLOCKED_MAX_HEIGHT_CM, True))
        self.assertIn("maximum", check_write(UNLOCKED_MAX_HEIGHT_CM + 1, True))
        self.assertIsNotNone(check_write(0.5, True))

    def test_refuses_garbage(self):
        for bad in (math.nan, math.inf, -math.inf, None, "170", True):
            self.assertIsNotNone(check_write(bad, True), bad)


class TestReportedCm(unittest.TestCase):
    def test_exact_no_rounding(self):
        self.assertAlmostEqual(reported_cm(1.734), 173.4)

    def test_never_clamped(self):
        self.assertAlmostEqual(reported_cm(250.0), 25000.0)     # above 100 m
        self.assertAlmostEqual(reported_cm(0.005), 0.5)         # below 1 cm

    def test_unusable(self):
        for bad in (0, -1, math.nan, math.inf, None, "x"):
            self.assertIsNone(reported_cm(bad), bad)


class TestFormatting(unittest.TestCase):
    def test_units(self):
        self.assertEqual(format_height(170), "170 cm")
        self.assertEqual(format_height(173.44), "173.4 cm")
        self.assertEqual(format_height(1250), "12.5 m")
        self.assertEqual(format_height(10_000), "100 m")
        self.assertEqual(format_height(125_000), "1.25 km")

    def test_durations(self):
        self.assertEqual(describe_duration(45), "45 s")
        self.assertEqual(describe_duration(600), "10 min")
        self.assertEqual(describe_duration(5400), "1 h 30 min")
        self.assertEqual(format_duration(185), "3:05")
        self.assertEqual(format_duration(3723), "1:02:03")


class TestReportGate(unittest.TestCase):
    def test_adopts_when_nothing_was_sent(self):
        g = ReportGate(hold_s=1.0)
        self.assertEqual(g.offer(10.0, 10.0, 170.0), 170.0)

    def test_drops_reports_older_than_the_latest_send(self):
        g = ReportGate(hold_s=1.0)
        g.on_send(10.0)
        self.assertIsNone(g.offer(9.99, 10.01, 170.0))     # received before the send
        self.assertIsNone(g.release(11.5))

    def test_holds_then_releases_newest(self):
        g = ReportGate(hold_s=1.0)
        g.on_send(10.0)
        self.assertIsNone(g.offer(10.2, 10.2, 171.0))
        self.assertIsNone(g.offer(10.4, 10.4, 172.0))
        self.assertIsNone(g.offer(10.3, 10.5, 171.5))      # arrived late, older: ignored
        self.assertIsNone(g.release(10.9))                 # still holding
        self.assertEqual(g.release(11.1), 172.0)

    def test_new_send_invalidates_held_report(self):
        g = ReportGate(hold_s=1.0)
        g.on_send(10.0)
        g.offer(10.2, 10.2, 171.0)
        g.on_send(10.5)
        self.assertIsNone(g.release(11.6))

    def test_after_the_hold_reports_pass(self):
        g = ReportGate(hold_s=1.0)
        g.on_send(10.0)
        self.assertEqual(g.offer(11.5, 11.5, 180.0), 180.0)

    def test_drops_reports_seen_before_an_avatar_change(self):
        # An HTTP read asked for before the change answers with the OLD avatar.
        g = ReportGate(hold_s=1.0)
        g.on_avatar_change(20.0)
        self.assertIsNone(g.offer(19.9, 20.3, 150.0))
        self.assertEqual(g.offer(20.1, 20.4, 120.0), 120.0)

    def test_avatar_change_clears_an_older_held_report(self):
        g = ReportGate(hold_s=1.0)
        g.on_send(10.0)
        g.offer(10.2, 10.2, 171.0)
        g.on_avatar_change(10.5)
        self.assertIsNone(g.release(11.1))

    def test_slow_read_does_not_replace_a_newer_packet(self):
        # Read asked at 30.0, answered at 30.4; an OSC packet arrived at 30.2.
        g = ReportGate(hold_s=1.0)
        self.assertEqual(g.offer(30.2, 30.2, 180.0), 180.0)
        self.assertIsNone(g.offer(30.0, 30.4, 175.0))
        self.assertEqual(g.offer(30.5, 30.5, 181.0), 181.0)

    def test_reset_forgets_everything(self):
        g = ReportGate(hold_s=1.0)
        g.on_send(50.0)
        g.offer(50.5, 50.5, 1.0)
        g.reset()
        self.assertFalse(g.holding)
        self.assertEqual(g.offer(1.0, 1.0, 170.0), 170.0)


class TestHoldHeight(unittest.TestCase):
    def test_percent_grows_by_the_same_share_every_second(self):
        self.assertAlmostEqual(hold_height(170.0, 2.0, 5.0, SPEED_PERCENT, +1),
                               170.0 * 1.05 ** 2)

    def test_percent_shrink_takes_it_back_the_same_way(self):
        up = hold_height(170.0, 3.0, 5.0, SPEED_PERCENT, +1)
        self.assertAlmostEqual(hold_height(up, 3.0, 5.0, SPEED_PERCENT, -1), 170.0)

    def test_cm_per_second(self):
        self.assertAlmostEqual(hold_height(170.0, 1.5, 10.0, SPEED_CM, -1), 155.0)
        self.assertAlmostEqual(hold_height(170.0, 1.5, 10.0, SPEED_CM, +1), 185.0)

    def test_no_time_no_change(self):
        self.assertEqual(hold_height(170.0, 0.0, 5.0, SPEED_PERCENT, +1), 170.0)
        self.assertEqual(hold_height(170.0, -1.0, 5.0, SPEED_CM, +1), 170.0)


class TestPreserveTarget(unittest.TestCase):
    def test_ignores_new_avatar_report_stamped_just_before_change(self):
        h = HeightHistory()
        h.record(1.0, 150.0, "vrchat")       # the user's height
        h.record(4.95, 120.0, "vrchat")      # new avatar default, a hair before /avatar/change
        self.assertEqual(h.preserve_target(5.0, guard_s=0.3), 150.0)

    def test_ignores_everything_after_change(self):
        h = HeightHistory()
        h.record(1.0, 150.0, "vrchat")
        h.record(5.2, 120.0, "vrchat")
        self.assertEqual(h.preserve_target(5.0), 150.0)

    def test_own_sends_are_trusted_even_right_before(self):
        h = HeightHistory()
        h.record(1.0, 150.0, "vrchat")
        h.record(4.9, 160.0, "app")
        self.assertEqual(h.preserve_target(5.0, guard_s=0.3), 160.0)

    def test_picks_by_timestamp_not_arrival_order(self):
        h = HeightHistory()
        h.record(3.0, 155.0, "vrchat")
        h.record(2.0, 150.0, "vrchat")       # processed later, but older
        self.assertEqual(h.preserve_target(5.0), 155.0)

    def test_nothing_known(self):
        self.assertIsNone(HeightHistory().preserve_target(5.0))


class TestTransition(unittest.TestCase):
    def test_linear(self):
        t = Transition(100, 200, 10, CURVE_LINEAR)
        t.play(0.0)
        self.assertAlmostEqual(t.value(5.0), 150.0)
        self.assertEqual(t.value(10.0), 200.0)
        self.assertTrue(t.finished(10.0))
        self.assertEqual(t.value(99.0), 200.0)            # never overshoots

    def test_scale_curve_is_geometric(self):
        t = Transition(100, 10_000, 10, CURVE_SCALE)
        t.play(0.0)
        self.assertAlmostEqual(t.value(5.0), 1000.0)       # halfway in time = x10 of x100
        self.assertEqual(t.value(10.0), 10_000)

    def test_shrinking(self):
        t = Transition(200, 100, 4, CURVE_LINEAR)
        t.play(0.0)
        self.assertAlmostEqual(t.value(1.0), 175.0)

    def test_pause_stops_the_clock(self):
        t = Transition(100, 200, 10)
        t.play(0.0)
        t.pause(4.0)
        self.assertAlmostEqual(t.value(100.0), 140.0)      # frozen while paused
        t.play(100.0)
        self.assertAlmostEqual(t.value(103.0), 170.0)
        self.assertAlmostEqual(t.remaining(103.0), 3.0)

    def test_values_stay_between_endpoints(self):
        for curve in (CURVE_LINEAR, CURVE_SCALE):
            t = Transition(37.0, 9_000.0, 7.0, curve)
            t.play(0.0)
            for i in range(0, 71):
                v = t.value(i / 10)
                self.assertGreaterEqual(v, 37.0 - 1e-9)
                self.assertLessEqual(v, 9_000.0 + 1e-9)

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            Transition(100, 200, 0)
        with self.assertRaises(ValueError):
            Transition(math.nan, 200, 10)

    def test_interpolate_clamps_fraction(self):
        self.assertEqual(interpolate(1, 2, -1, CURVE_LINEAR), 1)
        self.assertEqual(interpolate(1, 2, 5, CURVE_LINEAR), 2)


class TestParseHeight(unittest.TestCase):
    """What the target field takes: what it shows, and what people type."""

    def test_units(self):
        self.assertEqual(parse_height("170"), 170.0)            # a bare number is cm
        self.assertEqual(parse_height("170 cm"), 170.0)
        self.assertEqual(parse_height("1.7 m"), 170.0)
        self.assertEqual(parse_height("50m"), 5000.0)
        self.assertEqual(parse_height("1.25 km"), 125_000.0)
        self.assertEqual(parse_height(" 12.5 M "), 1250.0)

    def test_decimal_comma_and_thousands(self):
        self.assertEqual(parse_height("1,7 m"), 170.0)
        self.assertEqual(parse_height("1,234.5 cm"), 1234.5)

    def test_what_the_field_shows_reads_back(self):
        for cm in (1.0, 173.4, 999.9, 1250.0, 5000.0, 99_999.0, 125_000.0, 10_000_000.0):
            self.assertAlmostEqual(parse_height(format_height(cm)), cm, places=6)

    def test_not_a_height(self):
        for text in ("", "m", "abc", "1.2.3 m", "5 ft", "-3 cm"):
            self.assertIsNone(parse_height(text))


class TestCheckRange(unittest.TestCase):
    """The height scale's MIN and MAX, as typed on the scale or in Settings."""

    def test_a_good_range(self):
        self.assertIsNone(check_range(1, 10_000, False))
        self.assertIsNone(check_range(50, 2000, False))
        self.assertIsNone(check_range(1, UNLOCKED_MAX_HEIGHT_CM, True))

    def test_refused_never_clamped(self):
        self.assertIn("limit", check_range(1, 50_000, False))
        self.assertIn("Unlock", check_range(1, 50_000, False))
        self.assertIn("maximum", check_range(1, 20_000_000, True))
        self.assertIn("minimum", check_range(0.5, 100, False))
        self.assertIn("below the top", check_range(500, 500, False))
        self.assertIn("below the top", check_range(800, 500, False))
        self.assertEqual(check_range(None, 500, False), "not a height")


class TestHeightScale(unittest.TestCase):
    """The log scale beside the figure, which is the height slider."""

    def test_ends_are_exact(self):
        self.assertEqual(scale_height(0.0, 1, 10_000), 1)
        self.assertEqual(scale_height(1.0, 1, 10_000), 10_000)
        self.assertEqual(scale_fraction(1, 1, 10_000), 0.0)
        self.assertEqual(scale_fraction(10_000, 1, 10_000), 1.0)

    def test_every_decade_gets_the_same_room(self):
        self.assertAlmostEqual(scale_fraction(10, 1, 10_000), 0.25)
        self.assertAlmostEqual(scale_fraction(1000, 1, 10_000), 0.75)
        self.assertAlmostEqual(scale_fraction(1_000_000, 1, 10_000_000), 6 / 7)

    def test_round_trip_is_close_and_tidy(self):
        for cm in (5, 50, 170, 1700, 9000):
            back = scale_height(scale_fraction(cm, 1, 10_000), 1, 10_000)
            self.assertLess(abs(back - cm) / cm, 0.01)
        self.assertEqual(scale_height(scale_fraction(234.567, 1, 10_000), 1, 10_000), 235.0)

    def test_out_of_range_is_pinned(self):
        self.assertEqual(scale_fraction(50_000, 1, 10_000), 1.0)
        self.assertEqual(scale_fraction(0.5, 1, 10_000), 0.0)
        self.assertEqual(scale_height(1.7, 1, 10_000), 10_000)
        self.assertEqual(scale_height(-3, 1, 10_000), 1)

    def test_tidy_heights(self):
        self.assertEqual(tidy_height(234.567), 235.0)
        self.assertEqual(tidy_height(5123.4), 5120.0)
        self.assertEqual(tidy_height(1.234), 1.23)

    def test_decades(self):
        self.assertEqual(scale_decades(1, 10_000), [1.0, 10.0, 100.0, 1000.0, 10_000.0])
        self.assertEqual(scale_decades(30, 2000), [100.0, 1000.0])


class TestMenuInput(unittest.TestCase):
    """The in-VRChat menu's parameters -> what the app does."""

    def setUp(self):
        self.m = MenuInput(guard_s=1.0, debounce_s=0.15)

    def test_held_buttons_report_down_and_up(self):
        self.assertEqual(self.m.offer(MENU_GROW, True, 10.0), ("grow", 1))
        self.assertTrue(self.m.held["grow"])
        self.assertEqual(self.m.offer(MENU_GROW, False, 12.0), ("grow", 0))
        self.assertFalse(self.m.held["grow"])
        self.assertEqual(self.m.offer(MENU_SHRINK, True, 13.0), ("shrink", 1))

    def test_one_shot_buttons_act_on_the_press_only(self):
        self.assertEqual(self.m.offer(MENU_PLAY, True, 10.0), ("play", 0))
        self.assertIsNone(self.m.offer(MENU_PLAY, False, 10.3))
        self.assertEqual(self.m.offer(MENU_STOP, 1, 11.0), ("stop", 0))

    def test_slot_buttons_carry_their_number(self):
        self.assertEqual(self.m.offer(MENU_LOAD, 3, 10.0), ("load", 3))
        self.assertIsNone(self.m.offer(MENU_LOAD, 0, 10.2))
        self.assertEqual(self.m.offer(MENU_SAVE, 2, 11.0), ("save", 2))
        self.assertEqual(self.m.offer(MENU_SAVE, 4, 11.1), ("save", 4))   # 2 -> 4 at once

    def test_the_routers_second_copy_is_not_a_second_press(self):
        # with the 518 router every packet arrives twice, a few ms apart
        self.assertEqual(self.m.offer(MENU_LOAD, 1, 10.000), ("load", 1))
        self.assertIsNone(self.m.offer(MENU_LOAD, 1, 10.002))
        self.assertIsNone(self.m.offer(MENU_LOAD, 0, 10.040))
        self.assertIsNone(self.m.offer(MENU_LOAD, 1, 10.042))         # late copy of the tap
        self.assertIsNone(self.m.offer(MENU_LOAD, 0, 10.044))
        self.assertEqual(self.m.offer(MENU_LOAD, 1, 10.5), ("load", 1))  # a real second press

    def test_nothing_acts_while_a_new_avatar_loads(self):
        self.m.on_avatar_change(20.0)
        self.assertIsNone(self.m.offer(MENU_PLAY, True, 20.2))
        self.assertIsNone(self.m.offer(MENU_GROW, True, 20.3))
        self.assertFalse(self.m.held["grow"])
        self.assertEqual(self.m.offer(MENU_GROW, False, 20.4), ("grow", 0))  # a release counts
        self.assertEqual(self.m.offer(MENU_PLAY, False, 21.5), None)
        self.assertEqual(self.m.offer(MENU_PLAY, True, 21.8), ("play", 0))

    def test_avatar_change_and_reset_let_go(self):
        self.m.offer(MENU_GROW, True, 10.0)
        self.m.on_avatar_change(11.0)
        self.assertFalse(self.m.held["grow"])
        self.m.offer(MENU_SHRINK, True, 13.0)
        self.m.reset()
        self.assertFalse(self.m.held["shrink"])

    def test_other_parameters_and_bad_values_are_ignored(self):
        self.assertIsNone(self.m.offer("HeightShift/Nope", True, 10.0))
        self.assertIsNone(self.m.offer("VRCEmote", 3, 10.0))
        self.assertIsNone(self.m.offer(MENU_LOAD, "2", 10.0))
        self.assertIsNone(self.m.offer(MENU_LOAD, float("nan"), 10.0))


if __name__ == "__main__":
    unittest.main()
