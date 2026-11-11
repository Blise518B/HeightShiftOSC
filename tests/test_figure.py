"""The size comparison on its height scale: eyes at the height on the scale, picking the
target (pointer, a click or drag along the scale, a head) without ever
setting a height, saved heights, the ratio text, small figures, the stage
shrinking for a narrow window, and the easing that keeps a stream of updates
smooth. Runs Qt offscreen."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from constants import MIN_HEIGHT_CM, UNLOCKED_MAX_HEIGHT_CM  # noqa: E402
from height_logic import format_height  # noqa: E402
from ui.figure import (  # noqa: E402
    BASE_PX,
    EYE_FROM_TOP,
    FIT_MIN,
    POINTER_DX,
    POINTER_W,
    RING_PX,
    SizeComparison,
    decade_label,
    ratio_text,
    smooth_damp,
    solid_amount,
)


class RatioTextTest(unittest.TestCase):
    def test_bigger_and_smaller(self):
        self.assertEqual(ratio_text(170, 5000), ("×29.4", "bigger"))
        self.assertEqual(ratio_text(5000, 170), ("×29.4", "smaller"))
        self.assertEqual(ratio_text(100, 150), ("×1.50", "bigger"))

    def test_huge_ratio_reads_in_full(self):
        self.assertEqual(ratio_text(MIN_HEIGHT_CM, UNLOCKED_MAX_HEIGHT_CM),
                         ("×10,000,000", "bigger"))

    def test_same_height(self):
        self.assertEqual(ratio_text(170, 170), ("=", "same height"))
        self.assertEqual(ratio_text(170, 170.5), ("=", "same height"))

    def test_nothing_to_compare(self):
        self.assertEqual(ratio_text(None, 170), ("", ""))


class LabelsAndSolidTest(unittest.TestCase):
    def test_the_scale_prints_powers_of_ten_plainly(self):
        self.assertEqual([decade_label(v) for v in (1, 10, 100, 1000, 10_000, 100_000, 10_000_000)],
                         ["1 cm", "10 cm", "1 m", "10 m", "100 m", "1 km", "100 km"])

    def test_a_small_now_turns_solid_without_a_jump(self):
        self.assertEqual(solid_amount(80.0), 0.0)
        self.assertEqual(solid_amount(10.0), 1.0)
        values = [solid_amount(40 - i * 0.5) for i in range(33)]
        self.assertEqual(values, sorted(values))
        self.assertLess(max(b - a for a, b in zip(values, values[1:])), 0.08)


class EasingTest(unittest.TestCase):
    def test_reaches_the_goal_without_overshooting(self):
        x, v, seen = 0.0, 0.0, []
        for _ in range(120):
            x, v = smooth_damp(x, 1.0, v, 0.2, 1 / 60)
            seen.append(x)
        self.assertAlmostEqual(seen[-1], 1.0, places=3)
        self.assertLessEqual(max(seen), 1.0)
        self.assertEqual(seen, sorted(seen))

    def test_a_goal_moving_ten_times_a_second_gives_one_smooth_motion(self):
        # A transition: the goal steps up every 100 ms. The shown value must
        # keep moving forward every frame — no stop-and-go at each tick.
        x, v, goal, speeds = 0.0, 0.0, 0.0, []
        for frame in range(240):
            if frame % 6 == 0:
                goal += 0.1
            before = x
            x, v = smooth_damp(x, goal, v, 0.2, 1 / 60)
            if frame > 30:
                speeds.append(x - before)
        self.assertGreater(min(speeds), 0.0)
        self.assertLess(max(speeds) / min(speeds), 2.0)


class WidgetTest(unittest.TestCase):
    def setUp(self):
        self.fig = SizeComparison()
        self.fig.resize(500, 200)

    def test_eases_in_log_space_and_settles(self):
        self.fig.set_heights(100.0, 1000.0, animate=False)
        self.fig.show()
        self.fig.set_heights(1000.0, 1000.0, animate=True)
        self.fig._timer.stop()
        self.fig.step(0.1)
        mid, _target = self.fig.shown_cm()
        self.assertGreater(mid, 100.0)
        self.assertLess(mid, 1000.0)
        for _ in range(200):
            if not self.fig.step(1 / 60):
                break
        self.assertAlmostEqual(self.fig.shown_cm()[0], 1000.0, places=3)
        self.fig.close()

    def test_snap_and_unknown(self):
        self.fig.set_heights(None, 5000.0, animate=False)
        self.assertEqual(self.fig.shown_cm(), (5000.0, 5000.0))
        self.fig.set_heights(170.0, 5000.0, animate=False)
        self.assertAlmostEqual(self.fig.shown_cm()[0], 170.0)

    def test_paints_every_case(self):
        for now, target in ((170, 5000), (5000, 170), (1, 10_000_000), (None, 200), (170, 170)):
            self.fig.set_heights(now, target, animate=False)
            self.assertFalse(self.fig.grab().isNull())
        # with the readouts: a lit head line, and the height under the mouse
        for hover, hover_cm in (("target", None), ("now", 300.0), (("head", "now"), None)):
            self.fig._hover, self.fig._hover_cm = hover, hover_cm
            self.assertFalse(self.fig.grab().isNull())


class FitTest(unittest.TestCase):
    """A narrow window shrinks the stage before the Height panel wraps."""

    def setUp(self):
        self.fig = SizeComparison()
        self.fig.set_range(1, 10_000, 10_000)
        self.fig.set_heights(170.0, 10_000.0, animate=False)

    def test_fit_for_a_width(self):
        full_w = self.fig.stage_size(1.0)[0]
        small_w = self.fig.stage_size(FIT_MIN)[0]
        self.assertLess(small_w, full_w)
        self.assertEqual(self.fig.fit_for(full_w + 500), 1.0)       # never bigger than full
        self.assertAlmostEqual(self.fig.fit_for(full_w), 1.0, delta=0.01)
        mid = self.fig.fit_for((full_w + small_w) / 2)
        self.assertTrue(FIT_MIN < mid < 1.0)
        self.assertLessEqual(self.fig.stage_size(mid)[0], (full_w + small_w) / 2)
        self.assertIsNone(self.fig.fit_for(small_w - 1))            # not even the smallest

    def test_a_shrunk_stage_keeps_everything_in_place(self):
        self.fig.set_fit(0.7)
        self.assertEqual((self.fig.width(), self.fig.height()), self.fig.stage_size(0.7))
        s = 1.0
        # her widest (eyes at MAX) still clears the target pointer and the
        # stage's edge, and her head the stage's top
        r = self.fig.figure_rect(self.fig.floor_y() - self.fig.y_of(10_000.0))
        self.assertGreaterEqual(r.left(), self.fig.axis_x() + (POINTER_DX + POINTER_W) * s)
        self.assertLessEqual(r.right(), self.fig.width())
        self.assertGreaterEqual(r.top(), 0.0)
        h_now, _h_target = self.fig.heights_px()
        self.assertAlmostEqual(self.fig.floor_y() - h_now, self.fig.y_of(170.0), delta=0.5)
        self.fig.set_fit(0.1)                                        # never below FIT_MIN
        self.assertEqual(self.fig.fit, FIT_MIN)
        self.fig.set_fit(5)
        self.assertEqual(self.fig.fit, 1.0)


class ScaleTest(unittest.TestCase):
    """The height scale the figures stand on. It only ever picks the target:
    drag the pointer, click or drag along the scale (the ring at your height
    included), or pull a head; click a saved height. It never sets a
    height — Go instant or Go timed (in the window) does."""

    def setUp(self):
        self.fig = SizeComparison()
        self.fig.set_range(1, 10_000, 10_000)
        self.fig.set_heights(170.0, 5000.0, animate=False)
        self.fig.set_saved(1, 30.0)
        self.fig.set_saved(2, None)
        self.fig.set_marks_enabled({1: (True, ""), 2: (False, "Empty")})
        self.seen = []
        for name in ("target_previewed", "target_committed", "load_requested"):
            getattr(self.fig, name).connect(lambda v, n=name: self.seen.append((n, v)))

    def at(self, cm, which="now"):
        return QPoint(round(self.fig.handle_x(which)), round(self.fig.y_of(cm)))

    def drag(self, start, end):
        QTest.mousePress(self.fig, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(self.fig, end)
        QTest.mouseRelease(self.fig, Qt.LeftButton, Qt.NoModifier, end)

    def names(self):
        return [n for n, _v in self.seen]

    def test_it_can_not_set_a_height(self):
        for name in ("now_previewed", "now_committed"):
            self.assertFalse(hasattr(self.fig, name))

    def test_dragging_the_ring_picks_a_target(self):
        # the ring only shows where you are; dragging from it picks the target
        self.drag(self.at(170.0), self.at(1000.0))
        self.assertEqual(self.names()[0], "target_previewed")
        self.assertEqual(self.names()[-1], "target_committed")
        picked = self.seen[-1][1]
        self.assertLess(abs(picked - 1000.0) / 1000.0, 0.03)
        self.assertEqual(picked, float(f"{picked:.3g}"))           # a tidy height
        self.assertEqual(self.fig._now_cm, 170.0)                  # you stay where you are

    def test_a_click_on_the_scale_picks_the_height_there(self):
        QTest.mouseClick(self.fig, Qt.LeftButton, Qt.NoModifier, self.at(600.0))
        self.assertEqual(self.names(), ["target_previewed", "target_committed"])
        self.assertLess(abs(self.seen[-1][1] - 600.0) / 600.0, 0.03)

    def test_hovering_the_scale_shows_where_a_click_would_pick(self):
        self.fig.show()
        QTest.mouseMove(self.fig, self.at(600.0))
        self.assertIsNotNone(self.fig._hover_cm)
        self.assertLess(abs(self.fig._hover_cm - 600.0) / 600.0, 0.03)
        self.assertEqual(self.seen, [])                            # a hover picks nothing
        self.fig.close()

    def test_the_pointer_sets_the_target(self):
        self.drag(self.at(5000.0, "target"), self.at(300.0, "target"))
        self.assertEqual(self.names(), ["target_previewed", "target_committed"])
        self.assertLess(abs(self.seen[-1][1] - 300.0) / 300.0, 0.03)

    def test_the_picked_height_shows_at_once_and_she_eases_after(self):
        # the pointer, its line and the height tag are at the pick at once;
        # only the figure takes its time getting there
        self.fig.show()
        QTest.mousePress(self.fig, Qt.LeftButton, Qt.NoModifier, self.at(5000.0, "target"))
        QTest.mouseMove(self.fig, self.at(300.0, "target"))
        self.fig._timer.stop()                                     # no frame has run yet
        picked = self.fig._drag_cm
        tags = [t for t in self.fig._readouts() if t[2]]           # the target's
        self.assertEqual(len(tags), 1)
        y, text, _strong = tags[0]
        self.assertAlmostEqual(y, self.fig.y_of(picked), delta=0.01)
        self.assertEqual(text, format_height(picked))
        self.assertGreater(self.fig.shown_cm()[1], 4000.0)          # she is still big
        QTest.mouseRelease(self.fig, Qt.LeftButton, Qt.NoModifier, self.at(300.0, "target"))
        self.fig.close()

    def test_a_new_target_from_outside_tags_at_once_too(self):
        # loaded, typed, or the window's answer: same — the tag doesn't trail her
        self.fig.show()
        self.fig.set_heights(170.0, 40.0, animate=True)
        self.fig._timer.stop()
        self.fig.step(0.03)
        self.fig._hover = "target"
        self.assertGreater(self.fig.shown_cm()[1], 41.0)            # on her way down
        (y, text, _strong), = [t for t in self.fig._readouts() if t[2]]
        self.assertAlmostEqual(y, self.fig.y_of(40.0), delta=0.01)
        self.assertEqual(text, format_height(40.0))
        self.fig.close()

    def test_grab_areas_are_big_enough_for_vr(self):
        # a laser pointer shakes: a press well off a handle still takes it
        hit, ax = self.fig._hit, self.fig.axis_x()
        y_target, y_now = self.fig.y_of(5000.0), self.fig.y_of(170.0)
        self.assertEqual(hit(QPointF(ax + POINTER_DX + 1, y_target + 14)), "target")
        self.assertEqual(hit(QPointF(ax + POINTER_DX + POINTER_W + 12, y_target - 14)), "target")
        self.assertEqual(hit(QPointF(self.fig.figure_x(), y_now + 9)), ("head", "now"))
        self.assertEqual(hit(QPointF(ax + RING_PX + 4, y_now)), "now")
        self.assertEqual(hit(QPointF(ax - 16, self.fig.y_of(600.0))), ("track",))
        self.assertEqual(hit(QPointF(ax + 11, self.fig.y_of(30.0))), ("mark", 1))
        # … and the saved mark stays the mark, with the pointer right beside it
        self.fig.set_heights(170.0, 30.0, animate=False)
        self.assertEqual(hit(QPointF(ax, self.fig.y_of(30.0))), ("mark", 1))

    def test_a_dragged_target_snaps_onto_a_saved_height(self):
        near = QPoint(self.at(30.0).x(), self.at(30.0).y() + 3)
        self.drag(self.at(5000.0, "target"), near)
        self.assertEqual(self.seen[-1], ("target_committed", 30.0))

    def test_clicking_a_saved_height_sets_it(self):
        QTest.mouseClick(self.fig, Qt.LeftButton, Qt.NoModifier, self.at(30.0))
        self.assertEqual(self.seen, [("load_requested", 1)])

    def test_nothing_is_picked_while_a_transition_runs(self):
        self.fig.set_target_locked(True, "Stop the transition first.")
        self.drag(self.at(170.0), self.at(1000.0))
        self.drag(self.at(5000.0, "target"), self.at(300.0, "target"))
        QTest.mouseClick(self.fig, Qt.LeftButton, Qt.NoModifier, self.at(600.0))
        head = QPoint(round(self.fig.figure_x()), round(self.fig.y_of(170.0)))
        self.drag(head, self.at(1000.0))
        self.assertEqual(self.seen, [])
        self.assertEqual(self.fig._tip("now"), "Stop the transition first.")

    def test_ends_are_the_range(self):
        self.assertEqual(self.fig.cm_at(self.fig.y_of(1.0)), 1.0)
        self.assertEqual(self.fig.cm_at(self.fig.y_of(10_000.0)), 10_000.0)
        self.assertEqual(self.fig.cm_at(-50), 10_000.0)            # above the top: MAX

    # --- typing MIN / MAX on the scale -------------------------------------
    def open_max(self):
        self.fig.show()
        r = self.fig._end_rect("hi")
        QTest.mouseClick(self.fig, Qt.LeftButton, Qt.NoModifier,
                         QPoint(round(r.center().x()), round(r.center().y())))
        self.ranges = []
        self.fig.range_committed.connect(lambda lo, hi: self.ranges.append((lo, hi)))
        return self.fig._edit

    def test_clicking_max_opens_it_for_typing(self):
        field = self.open_max()
        self.assertTrue(field.isVisible())
        self.assertEqual(field.text(), "100 m")
        self.fig.close()

    def test_a_typed_max_is_kept_on_enter(self):
        field = self.open_max()
        field.selectAll()
        QTest.keyClicks(field, "50 m")
        QTest.keyClick(field, Qt.Key_Return)
        self.assertEqual(self.ranges, [(1.0, 5000.0)])
        self.assertFalse(field.isVisible())
        self.fig.close()

    def test_an_impossible_max_is_refused_and_stays_open(self):
        field = self.open_max()
        field.selectAll()
        QTest.keyClicks(field, "500 m")                           # the limit is 100 m
        QTest.keyClick(field, Qt.Key_Return)
        self.assertEqual(self.ranges, [])
        self.assertTrue(field.isVisible())
        self.assertEqual(field.property("bad"), "true")
        self.assertIn("limit", field.toolTip())
        QTest.keyClick(field, Qt.Key_Escape)                      # keep what it was
        self.assertFalse(field.isVisible())
        self.assertEqual(self.ranges, [])
        self.fig.close()

    def test_her_eyes_are_at_her_height(self):
        # VRChat's height is eye height: the eye line, not the top of her
        # head, is on the scale at her height
        h_now, h_target = self.fig.heights_px()
        floor = self.fig.floor_y()
        self.assertAlmostEqual(floor - h_now, self.fig.y_of(170.0), delta=0.5)
        self.assertAlmostEqual(floor - h_target, self.fig.y_of(5000.0), delta=0.5)
        for h, cm in ((h_now, 170.0), (h_target, 5000.0)):
            r = self.fig.figure_rect(h)
            self.assertAlmostEqual(r.top() + EYE_FROM_TOP * r.height(), self.fig.y_of(cm),
                                   delta=0.5)
            self.assertLess(r.top(), self.fig.y_of(cm))           # her head is above it
        # eyes at MAX: her head still fits on the stage
        self.fig.set_heights(10_000.0, 10_000.0, animate=False)
        self.assertGreaterEqual(self.fig.figure_rect(self.fig.heights_px()[0]).top(), 0.0)

    def test_the_height_line_goes_round_her_face(self):
        h_now, _h_target = self.fig.heights_px()
        left, right = self.fig._head_edges(h_now)
        r = self.fig.figure_rect(h_now)
        self.assertTrue(r.left() < left < self.fig.figure_x() < right < r.right())

    def test_the_scale_bottom_still_shows_her(self):
        self.fig.set_heights(1.0, 1.0, animate=False)              # MIN
        self.assertGreaterEqual(min(self.fig.heights_px()), BASE_PX - 0.5)

    def test_pulling_her_head_picks_the_target(self):
        head = QPoint(round(self.fig.figure_x()), round(self.fig.y_of(170.0)))
        self.drag(head, self.at(1000.0))
        self.assertEqual(set(self.names()), {"target_previewed", "target_committed"})
        self.assertLess(abs(self.seen[-1][1] - 1000.0) / 1000.0, 0.03)

    def test_pulling_the_shadows_head_moves_the_target(self):
        head = QPoint(round(self.fig.figure_x()), round(self.fig.y_of(5000.0)))
        self.drag(head, self.at(2000.0))
        self.assertEqual(self.names(), ["target_previewed", "target_committed"])
        self.assertLess(abs(self.seen[-1][1] - 2000.0) / 2000.0, 0.03)


if __name__ == "__main__":
    unittest.main()
