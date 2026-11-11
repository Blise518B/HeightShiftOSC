"""The size comparison on its height scale, where the target is picked.

NOW and TARGET are two copies of the same figure, one in front of the other:
TARGET is her filled silhouette in a quiet green, standing behind; NOW is her
line drawing in the bright accent, in front of it. Growing towards a bigger
target, the lines fill the shadow; shrinking, the shadow sits inside the
lines. Equal heights are a filled, outlined figure.

Both stand ON the scale on the left. VRChat's height is EYE height, so each
stands with her eyes at her height on it: a hairline runs from the scale to
her head and on past it, and only a faint dotted line crosses her face. The scale is logarithmic — every decade
gets the same room, so 1 cm and 1000 m are both easy to see and to pick — and
it picks the target: its ends are the slider range, marked MIN and MAX,
or LIMIT when the top is the most that may be sent. Nothing on it sends a
height — picking only moves the target, and Go instant or Go timed (in the
window) takes you there. On it:
  * a ring at your height — it only shows where you are;
  * a soft pointer at the target — drag it, click or drag anywhere along the
    scale, or pull either head up or down, to pick the target (a light line
    with the height follows the mouse over the scale first);
  * the six saved heights as numbered marks — click one to load it as the
    target (or to go there, as its action says); a dragged target snaps
    onto a mark it comes close to;
  * its two ends: click MIN's or MAX's number to type a new one (Enter
    keeps it, Esc doesn't; a range that can't be is refused with why).
In a narrow window the whole stage shrinks (set_fit, down to FIT_MIN) before
the window puts the Height panel under it.
Because the scale is logarithmic the picture is not to scale (1.7 m next to
50 m looks far closer than 1 : 29): the window writes the ratio out.

Pure view: signals out (target_previewed / target_committed,
load_requested, range_committed), setters in. The figures ease from the size
they have to the new one, so a click, a transition's sends (30 a second by
default) or a held hotkey reads as growing, never as jumping. Everything that
marks a height — the ring, the pointer, their hairlines and the height tags —
is at the height at once; she grows into it.

The figure is OscGoesPurrr's Suits cat girl (`assets/figure.png`, same
author, MIT): white lines on transparency, tinted at paint time as OGP's
body_view does it. `assets/figure_fill.png` is her inside, made from it by
tools/make_figure_assets.py.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QElapsedTimer, QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QLineEdit, QSizePolicy, QToolTip, QWidget

from constants import MAX_HEIGHT_CM, MIN_HEIGHT_CM
from height_logic import (
    check_range,
    format_height,
    parse_height,
    scale_decades,
    scale_fraction,
    scale_height,
)

from .theme import SHADOW_ALPHA, colors, resource_path, text_scale

LINES_FILE = "assets/figure.png"
FILL_FILE = "assets/figure_fill.png"
FIGURE_ASPECT = 401 / 1110            # width / height of the drawing

# the widget at text size 100 %; its width follows from its height
STAGE_HEIGHT = 470
FIT_MIN = 0.58                        # how far the stage shrinks in a narrow window
AXIS_X = 80                           # the scale; its labels sit to its left
FIGURE_GAP = 4                        # between the target pointer and her widest
RIGHT_PAD = 6                         # right of her widest
HEAD_PAD = 4                          # above her head when her eyes are at MAX
END_WORD_PX = 30                      # the scale's top is never nearer the edge (MAX's word)
FLOOR_PAD = 12                        # room under the floor line (MIN's word)
BASE_PX = 14                          # her eye height at the scale's bottom (MIN): never less
# VRChat's height is eye height: she stands with her eyes at her height. No
# eyes are drawn on her; this is where they sit, just under the fringe, and
# how wide her head is there (hair included), measured on assets/figure.png.
EYE_FROM_TOP = 150 / 1110             # down from the drawing's top
HEAD_SPAN = (107 / 401, 277 / 401)    # her head's left and right edge, across the drawing
# Grab areas, VR-sized (a laser pointer shakes): how far off a thing a press still takes it
GRAB_PX = 16                          # the target pointer, above or below it
GRAB_RIGHT_PX = 14                    # … and right of its end
LINE_GRAB_PX = 10                     # a head line (pull a head), above or below it
TRACK_GRAB_PX = 18                    # the scale, left of it (right: as far as the pointer's)
DOT_GRAB_PX = 5                       # the ring and the saved marks, round their edge
POINTER_DX = 10                       # the target pointer's tip, right of the scale
POINTER_W = 13                        # … and how far right it reaches from there
RING_PX = 9.5                         # the NOW ring's radius: round a mark, not over it
SOLID_BELOW_PX = 40                   # a smaller NOW turns from lines into a bright solid …
SOLID_FULL_PX = 24                    # … fully solid from here down (thin lines vanish)
MARK_PX = 7                           # a saved-height mark's radius
SNAP_PX = 6                           # a dragged target this near a mark snaps onto it
GHOST_ALPHA = 0.55                    # NOW's lines while the height isn't read yet

SMOOTH_TIME_S = 0.07                  # her easing: smooths 30 sends a second, settles in ~0.2 s
FRAME_MS = 16                         # 60 fps while the window has the focus
UNFOCUSED_FRAME_MS = 50               # 20 fps while another one has it (OscGoesPurrr's)
SETTLED = 1e-3                        # in log10(cm): 0.23 %, a third of a pixel at 150 px


# ----------------------------------------------------------------------
# The picture's maths, without Qt (tests/test_figure.py)
# ----------------------------------------------------------------------


def _usable(cm) -> bool:
    return isinstance(cm, (int, float)) and math.isfinite(cm) and cm > 0


def ratio_text(now_cm: Optional[float], target_cm: Optional[float]) -> Tuple[str, str]:
    """('×29.4', 'bigger') — how the target compares with now. ('', '') when
    there's nothing to compare."""
    if not (_usable(now_cm) and _usable(target_cm)):
        return "", ""
    big, small = max(now_cm, target_cm), min(now_cm, target_cm)
    r = big / small
    if r < 1.005:
        return "=", "same height"
    if r >= 100:
        num = f"{r:,.0f}"
    elif r >= 10:
        num = f"{r:.1f}"
    else:
        num = f"{r:.2f}"
    return f"×{num}", ("bigger" if target_cm > now_cm else "smaller")


def solid_amount(h_px: float) -> float:
    """How much a small NOW figure is drawn as a bright solid instead of
    lines: 0 above SOLID_BELOW_PX, 1 from SOLID_FULL_PX down, eased."""
    if h_px >= SOLID_BELOW_PX:
        return 0.0
    if h_px <= SOLID_FULL_PX:
        return 1.0
    x = (SOLID_BELOW_PX - h_px) / (SOLID_BELOW_PX - SOLID_FULL_PX)
    return x * x * (3.0 - 2.0 * x)


def decade_label(cm: float) -> str:
    """A power of ten as the scale prints it: 1 cm, 10 cm, 1 m … 100 km."""
    if cm >= 100_000:
        return f"{cm / 100_000:g} km"
    if cm >= 100:
        return f"{cm / 100:g} m"
    return f"{cm:g} cm"


def smooth_damp(current: float, goal: float, velocity: float, smooth_time: float,
                dt: float) -> Tuple[float, float]:
    """A critically damped spring towards `goal` (Game Programming Gems 4,
    ch. 1.10). It keeps its speed when the goal moves on, so ten new goals
    a second still read as one smooth motion — an eased tween restarted on
    every tick would surge and brake ten times a second instead."""
    smooth_time = max(1e-4, smooth_time)
    omega = 2.0 / smooth_time
    x = omega * dt
    decay = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x)
    change = current - goal
    temp = (velocity + omega * change) * dt
    velocity = (velocity - omega * temp) * decay
    out = goal + (change + temp) * decay
    if (goal - current > 0.0) == (out > goal):        # never overshoot
        out, velocity = goal, 0.0
    return out, velocity


# ----------------------------------------------------------------------
# The widget
# ----------------------------------------------------------------------


class _Eased:
    """One height, eased in log space: 1 m -> 50 m takes as long and looks
    as even as 1 cm -> 50 cm."""

    def __init__(self) -> None:
        self.goal: Optional[float] = None       # log10(cm)
        self.goal_cm: Optional[float] = None
        self.shown: Optional[float] = None
        self.velocity = 0.0

    def aim(self, cm: Optional[float]) -> None:
        self.goal_cm = float(cm) if _usable(cm) else None
        self.goal = math.log10(cm) if self.goal_cm is not None else None
        if self.shown is None:
            self.shown, self.velocity = self.goal, 0.0

    def snap(self) -> None:
        self.shown, self.velocity = self.goal, 0.0

    def step(self, dt: float) -> bool:
        """Moves on; True while still moving."""
        if self.goal is None or self.shown is None:
            self.shown, self.velocity = self.goal, 0.0
            return False
        self.shown, self.velocity = smooth_damp(self.shown, self.goal, self.velocity,
                                                SMOOTH_TIME_S, dt)
        if abs(self.shown - self.goal) < SETTLED and abs(self.velocity) < SETTLED:
            self.snap()
            return False
        return True

    @property
    def cm(self) -> Optional[float]:
        if self.shown is None:
            return None
        if self.shown == self.goal:
            return self.goal_cm             # settled: exactly the height given
        return 10.0 ** self.shown


class SizeComparison(QWidget):
    """NOW in front of TARGET, standing on the height scale that picks the
    target (see the module doc)."""

    target_previewed = Signal(float)    # the target is being picked (mouse held)
    target_committed = Signal(float)    # let go: this is the target (nothing is sent)
    load_requested = Signal(int)        # a saved-height mark was clicked: load it as target
    range_committed = Signal(float, float)   # MIN / MAX typed on the scale: (lo, hi)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self._now = _Eased()
        self._target = _Eased()
        self._now_cm: Optional[float] = None         # the real heights (the handles)
        self._target_cm: Optional[float] = None
        self._known = 0.0                            # 0 ghost .. 1 known, eased too
        self._known_goal = 0.0
        self._sources = {"lines": QImage(resource_path(LINES_FILE)),
                         "fill": QImage(resource_path(FILL_FILE))}
        self._mips: Dict[Tuple[str, int], List[QPixmap]] = {}
        # the scale
        self._lo, self._hi = float(MIN_HEIGHT_CM), float(MAX_HEIGHT_CM)
        self._limit = float(MAX_HEIGHT_CM)
        self._saved: Dict[int, Optional[float]] = {}
        self._mark_ok: Dict[int, Tuple[bool, str]] = {}
        self._target_locked, self._target_why = False, ""
        self._drag: Optional[str] = None             # "target" while the mouse is held
        self._drag_cm: Optional[float] = None
        self._hover = None                           # see _hit
        self._hover_cm: Optional[float] = None       # the height under the mouse on the scale
        self._fit = 1.0                              # FIT_MIN..1: how big the stage is
        # typing a new MIN or MAX right on the scale
        self._edit = QLineEdit(self)
        self._edit.setObjectName("ScaleEdit")
        self._edit.hide()
        self._edit.installEventFilter(self)
        self._edit.returnPressed.connect(lambda: self._finish_edit(keep_open=True))
        self._editing: Optional[str] = None          # "lo" / "hi" while it is open

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._frame)
        self._clock = QElapsedTimer()
        self.apply_scale()

    def apply_scale(self) -> None:
        """Follow the text size (ui-style.md: usable from VR)."""
        w, h = self.stage_size()
        self.setFixedSize(w, h)
        self.update()

    def _stage_w(self, fit: float) -> float:
        """The stage's width at this fit, unrounded: the labels, the scale,
        the pointer and her at her tallest."""
        s = text_scale()
        tallest = STAGE_HEIGHT * s * fit - (HEAD_PAD + FLOOR_PAD) * s    # drawn, eyes at MAX
        return ((AXIS_X + POINTER_DX + POINTER_W + FIGURE_GAP + RIGHT_PAD) * s
                + tallest * FIGURE_ASPECT)

    def stage_size(self, fit: Optional[float] = None) -> Tuple[int, int]:
        """(width, height) in px at this fit (default: the current one)."""
        fit = self._fit if fit is None else fit
        return math.ceil(self._stage_w(fit)), round(STAGE_HEIGHT * text_scale() * fit)

    def fit_for(self, width: float) -> Optional[float]:
        """The biggest fit (FIT_MIN..1) whose stage is at most `width` px
        wide; None when not even FIT_MIN's is."""
        w0, w1 = self._stage_w(0.0), self._stage_w(1.0)
        fit = min(1.0, (width - w0) / (w1 - w0))
        while fit >= FIT_MIN and self.stage_size(fit)[0] > width:
            fit -= 0.002                              # rounding
        return fit if fit >= FIT_MIN else None

    def set_fit(self, fit: float) -> None:
        """Shrink (or grow back) the whole stage, for a narrow window."""
        fit = min(1.0, max(FIT_MIN, float(fit)))
        if self.stage_size(fit) != self.stage_size():
            self._fit = fit
            self.apply_scale()
        else:
            self._fit = fit

    @property
    def fit(self) -> float:
        return self._fit

    # --- feeding -------------------------------------------------------

    def set_heights(self, now_cm: Optional[float], target_cm: Optional[float],
                    animate: bool = True) -> None:
        self._now_cm = now_cm if _usable(now_cm) else None
        self._target_cm = target_cm if _usable(target_cm) else None
        self._known_goal = 1.0 if self._now_cm is not None else 0.0
        self._aim(animate)

    def set_range(self, lo: float, hi: float, limit: float) -> None:
        """The scale's ends (the slider range) and the most that may be sent."""
        self._lo, self._hi, self._limit = float(lo), float(hi), float(limit)
        self.update()

    def set_saved(self, num: int, cm: Optional[float]) -> None:
        self._saved[num] = cm if _usable(cm) else None
        self.update()

    def set_marks_enabled(self, ok: Dict[int, Tuple[bool, str]]) -> None:
        """Which saved heights may be loaded as the target now, and why not."""
        self._mark_ok = dict(ok)
        self.update()

    def set_target_locked(self, locked: bool, why: str = "") -> None:
        """While a transition runs, the target can't be picked (and why)."""
        self._target_locked, self._target_why = bool(locked), why
        if locked and self._drag is not None:
            self._drag = self._drag_cm = None
            self._aim(True)
        if locked:
            self._hover_cm = None
        self.update()

    @property
    def dragging(self) -> Optional[str]:
        return self._drag

    def _shown(self, which: str) -> Optional[float]:
        """A height as drawn: the target being picked while the mouse is held,
        else the real one."""
        if self._drag == which:
            return self._drag_cm
        return self._now_cm if which == "now" else self._target_cm

    def _aim(self, animate: bool) -> None:
        now, target = self._shown("now"), self._shown("target")
        # Not read yet: the ghost stands as tall as the target, so the
        # picture claims no ratio it doesn't know.
        self._now.aim(now if now is not None else target)
        self._target.aim(target if target is not None else now)
        if not animate or not self.isVisible() or self.window().isMinimized():
            self.snap()                # nobody sees the easing: no frames for it
            return
        if not self._timer.isActive():
            self._clock.start()
            self._timer.start()
        self.update()

    def snap(self) -> None:
        """Straight to the goal sizes (first show, screenshots, tests)."""
        self._now.snap()
        self._target.snap()
        self._known = self._known_goal
        self._timer.stop()
        self.update()

    def step(self, dt: float) -> bool:
        """Advances the easing by `dt` seconds; True while still moving."""
        moving = self._now.step(dt) | self._target.step(dt)
        if self._known != self._known_goal:
            k = 1.0 - math.exp(-dt / 0.12)
            self._known += (self._known_goal - self._known) * k
            if abs(self._known - self._known_goal) < 0.01:
                self._known = self._known_goal
            else:
                moving = True
        return moving

    def shown_cm(self) -> Tuple[Optional[float], Optional[float]]:
        return self._now.cm, self._target.cm

    def _frame(self) -> None:
        if self.window().isMinimized():
            self.snap()
            return
        dt = min(0.1, self._clock.restart() / 1000.0)
        if not self.step(dt):
            self._timer.stop()
        interval = FRAME_MS if self.window().isActiveWindow() else UNFOCUSED_FRAME_MS
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)
        self.update()

    # --- geometry ------------------------------------------------------

    def floor_y(self) -> float:
        return self.height() - FLOOR_PAD * text_scale()

    def axis_x(self) -> float:
        return AXIS_X * text_scale()

    def figure_x(self) -> float:
        """Where she stands: her widest just clears the target pointer."""
        s = text_scale()
        tallest = self.floor_y() - HEAD_PAD * s                         # drawn, eyes at MAX
        return (self.axis_x() + (POINTER_DX + POINTER_W + FIGURE_GAP) * s
                + tallest * FIGURE_ASPECT / 2)

    def handle_x(self, which: str) -> float:
        """Where a handle sits: the ring on the scale, the pointer right of it."""
        return self.axis_x() + (0.0 if which == "now" else (POINTER_DX + 7.0) * text_scale())

    def _scale_ends(self) -> Tuple[float, float]:
        """(y of the bottom = MIN, y of the top = MAX). The top leaves room
        for her head above her eyes when they are at MAX."""
        s = text_scale()
        floor = self.floor_y()
        top = floor - (1.0 - EYE_FROM_TOP) * (floor - HEAD_PAD * s)
        return floor - BASE_PX * s, max(top, END_WORD_PX * s)

    def y_of(self, cm: float) -> float:
        bottom, top = self._scale_ends()
        return bottom - scale_fraction(cm, self._lo, self._hi) * (bottom - top)

    def cm_at(self, y: float) -> float:
        bottom, top = self._scale_ends()
        return scale_height((bottom - y) / max(1.0, bottom - top), self._lo, self._hi)

    def heights_px(self) -> Tuple[float, float]:
        """The two figures' eye heights in px: her eyes at her height on the
        scale (figure_rect gives the drawing, whose head reaches above)."""
        floor = self.floor_y()
        return tuple((floor - self.y_of(v)) if v is not None else 0.0
                     for v in (self._now.cm, self._target.cm))

    @staticmethod
    def drawn_px(eye_px: float) -> float:
        """The drawing's height for an eye height: her head is above her eyes."""
        return eye_px / (1.0 - EYE_FROM_TOP)

    def figure_rect(self, eye_px: float) -> QRectF:
        """Where the drawing goes for an eye height (standing on the floor)."""
        h = self.drawn_px(eye_px)
        w = h * FIGURE_ASPECT
        return QRectF(self.figure_x() - w / 2, self.floor_y() - h, w, h)

    def _head_edges(self, eye_px: float) -> Tuple[float, float]:
        """Her head's left and right edge at her eye line, in px."""
        r = self.figure_rect(eye_px)
        return r.left() + HEAD_SPAN[0] * r.width(), r.left() + HEAD_SPAN[1] * r.width()

    # --- input ---------------------------------------------------------

    def _hit(self, pos):
        """What is under the mouse: "target" (the pointer or the shadow's
        head), ("mark", n), ("end", "lo"/"hi"), "now" (the ring: it only
        shows), ("head", "now") (her head), ("track",) (along the scale), or
        None. Everything but the ends and marks picks the target."""
        x, y = pos.x(), pos.y()
        ax, s = self.axis_x(), text_scale()
        reach = ax + (POINTER_DX + POINTER_W + GRAB_RIGHT_PX) * s      # the pointer's, rightwards
        v = self._shown("target")
        if v is not None and abs(y - self.y_of(v)) <= GRAB_PX * s \
                and ax + (POINTER_DX - 1) * s <= x <= reach:
            return "target"
        for n, mv in self._saved.items():
            if mv is not None and self._lo <= mv <= self._hi \
                    and math.hypot(x - ax, y - self.y_of(mv)) <= (MARK_PX + DOT_GRAB_PX) * s:
                return ("mark", n)
        for which in ("hi", "lo"):
            if self._end_rect(which).contains(QPointF(x, y)):
                return ("end", which)
        now = self._now_cm
        if now is not None and self._lo <= now <= self._hi \
                and math.hypot(x - ax, y - self.y_of(now)) <= (RING_PX + DOT_GRAB_PX) * s:
            return "now"
        # a head, along its hairline: pull it to pick the target
        for which, hit in (("target", "target"), ("now", ("head", "now"))):
            hv = self._shown(which)
            if hv is None:
                continue
            hy = self.y_of(hv)
            half = self.drawn_px(self.floor_y() - hy) * FIGURE_ASPECT / 2
            if abs(y - hy) <= LINE_GRAB_PX * s \
                    and ax + 12 * s <= x <= self.figure_x() + half + GRAB_RIGHT_PX * s:
                return hit
        bottom, top = self._scale_ends()
        if ax - TRACK_GRAB_PX * s <= x <= reach \
                and top - GRAB_PX * s <= y <= bottom + GRAB_PX * s:
            return ("track",)
        return None

    def _end_rect(self, which: str) -> QRectF:
        """Where MIN's or MAX's number and its word (above MAX, below MIN)
        sit, left of the scale."""
        s = text_scale()
        y = self.y_of(self._hi if which == "hi" else self._lo)
        left = 2 * s
        top, bottom = (y - 27 * s, y + 11 * s) if which == "hi" else (y - 11 * s, y + 26 * s)
        return QRectF(left, top, self.axis_x() - 9 * s - left, bottom - top)

    def _picks(self, hit) -> bool:
        """Whether pressing here picks the target (not while it is locked)."""
        return self._picks_when_free(hit) and not self._target_locked

    def _cm_under(self, y: float) -> float:
        """The height at `y` on the scale; the saved marks are magnetic."""
        for v in self._saved.values():
            if v is not None and self._lo <= v <= self._hi \
                    and abs(self.y_of(v) - y) <= SNAP_PX * text_scale():
                return v
        bottom, top = self._scale_ends()
        return self.cm_at(min(bottom, max(top, y)))

    def set_click_action(self, action: str) -> None:
        """What a pick on the scale leads to (the window's mode switch) — only
        the tooltips say it; the picking itself is the same."""
        self._click_action = action

    def _tip(self, hit) -> str:
        after = {
            "instant": "and you go there at once.",
            "timed": "and the timed transition takes you there.",
        }.get(getattr(self, "_click_action", "select"),
              "then Go instant or Go timed. Nothing is sent until then.")
        if self._target_locked and self._picks_when_free(hit):
            return self._target_why
        if hit == "now":
            here = f"You are {format_height(self._now_cm)} now" if self._now_cm else "You"
            return f"{here}. Click or drag along the scale to pick a target, {after}"
        if hit == "target":
            return f"Drag to pick the target, {after}"
        if hit == ("head", "now"):
            return f"Pull her head up or down to pick a target from here, {after}"
        if hit == ("track",):
            return f"Click or drag to pick the target here, {after}"
        if isinstance(hit, tuple) and hit[0] == "end":
            if hit[1] == "hi":
                return (f"The scale's top: {format_height(self._hi)}. Click to type another "
                        "(the most the ring and the pointer reach).")
            return (f"The scale's bottom: {format_height(self._lo)}. Click to type another "
                    "(the least the ring and the pointer reach).")
        if isinstance(hit, tuple) and hit[0] == "mark":
            n = hit[1]
            ok, why = self._mark_ok.get(n, (False, ""))
            v = self._saved.get(n)
            if ok and v is not None:
                return f"Saved height {n}: {format_height(v)} — click to load it as the target."
            return why or f"Saved height {n}"
        return ("The height scale: click or drag along it (or pull a head) to pick the "
                "target, or click a numbered saved height to load it. Nothing is sent "
                "until Go instant or Go timed.")

    @staticmethod
    def _picks_when_free(hit) -> bool:
        """Whether pressing here picks the target, while that is allowed."""
        return hit in ("target", "now") or hit in (("head", "now"), ("track",))

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position()
        hit = self._hit(pos)
        if self._picks(hit):
            if hit == "target" and self._target_cm is not None:
                start = self._target_cm               # taken where it is
            elif hit == ("head", "now") and self._now_cm is not None:
                start = self._now_cm                  # pulled out of her head
            else:
                start = self._cm_under(pos.y())       # the height under the mouse
            self._drag, self._drag_cm, self._hover_cm = "target", start, None
            self._aim(True)
            if start != self._target_cm:
                self.target_previewed.emit(start)
        elif isinstance(hit, tuple) and hit[0] == "end":
            self.start_range_edit(hit[1])
        elif isinstance(hit, tuple) and hit[0] == "mark" \
                and self._mark_ok.get(hit[1], (False, ""))[0]:
            self.load_requested.emit(hit[1])

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.position()
        if self._drag is not None:
            cm = self._cm_under(pos.y())
            if cm != self._drag_cm:
                self._drag_cm = cm
                self._aim(True)
                self.target_previewed.emit(cm)
            return
        hit = self._hit(pos)
        # a light line with the height follows the mouse along the scale
        hover_cm = self._cm_under(pos.y()) if self._picks(hit) and hit in (
            "now", ("track",)) else None
        if hover_cm != self._hover_cm:
            self._hover_cm = hover_cm
            self.update()
        if hit != self._hover:
            self._hover = hit
            if hit in ("target", ("head", "now")) and self._picks(hit):
                self.setCursor(Qt.SizeVerCursor)
            elif self._picks(hit) or isinstance(hit, tuple) and (
                    hit[0] == "end" or hit[0] == "mark"
                    and self._mark_ok.get(hit[1], (False, ""))[0]):
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.unsetCursor()
            self.setToolTip(self._tip(hit))
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() != Qt.LeftButton or self._drag is None:
            super().mouseReleaseEvent(event)
            return
        cm = self._drag_cm
        self._drag = self._drag_cm = None
        self._aim(True)                    # the real target until the window answers
        if cm is not None:
            self.target_committed.emit(cm)

    # --- typing MIN / MAX on the scale -------------------------------------

    def start_range_edit(self, which: str) -> None:
        """Open the field over MIN's ("lo") or MAX's ("hi") number."""
        s = text_scale()
        self._editing = which
        y = self.y_of(self._hi if which == "hi" else self._lo)
        w, h = round(74 * s), round(28 * s)          # fits left of the scale
        right = round(self.axis_x() - 6 * s)
        self._edit.setGeometry(right - w, round(y - h / 2), w, h)
        self._edit.setText(format_height(self._hi if which == "hi" else self._lo))
        self._set_edit_bad(False)
        self._edit.show()
        self._edit.raise_()
        self._edit.setFocus(Qt.MouseFocusReason)
        self._edit.selectAll()

    def _set_edit_bad(self, bad: bool, why: str = "") -> None:
        self._edit.setProperty("bad", "true" if bad else "false")
        self._edit.style().unpolish(self._edit)
        self._edit.style().polish(self._edit)
        self._edit.setToolTip(why)
        if bad:
            QToolTip.showText(self._edit.mapToGlobal(QPoint(0, self._edit.height())), why,
                              self._edit)

    def _finish_edit(self, keep_open: bool) -> bool:
        """Enter: keep a good value, or say why not and stay open. Leaving the
        field: keep a good value, else drop the change. True if kept."""
        which = self._editing
        if which is None:
            return False
        cm = parse_height(self._edit.text())
        lo, hi = (cm, self._hi) if which == "lo" else (self._lo, cm)
        err = "not a height" if cm is None else \
            check_range(lo, hi, unlocked=self._limit > MAX_HEIGHT_CM)
        if err:
            if keep_open:
                self._set_edit_bad(True, f"Can't: {err}. Esc keeps "
                                         f"{format_height(self._lo if which == 'lo' else self._hi)}.")
                return False
            self.cancel_range_edit()
            return False
        self._editing = None
        self._edit.hide()
        if (lo, hi) != (self._lo, self._hi):
            self.range_committed.emit(float(lo), float(hi))
        return True

    def cancel_range_edit(self) -> None:
        self._editing = None
        self._edit.hide()
        QToolTip.hideText()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self._edit and self._editing is not None:
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.cancel_range_edit()
                return True
            if event.type() == QEvent.FocusOut:
                self._finish_edit(keep_open=False)
        return super().eventFilter(obj, event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = self._hover_cm = None
        self.update()
        super().leaveEvent(event)

    # --- the picture ---------------------------------------------------

    def _mip_chain(self, kind: str, color: QColor) -> List[QPixmap]:
        """The drawing in `color` at full size and every half size down to a
        few px. Painting picks the next bigger one, so a figure shrinking
        frame by frame never shimmers (a one-step downscale skips lines)."""
        key = (kind, color.rgba())
        chain = self._mips.get(key)
        if chain is not None:
            return chain
        if len(self._mips) > 12:
            self._mips.clear()
        img = self._sources[kind].convertToFormat(QImage.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(img.rect(), color)
        p.end()
        chain = [QPixmap.fromImage(img)]
        while img.height() > 16:
            img = img.scaled(max(1, img.width() // 2), max(1, img.height() // 2),
                             Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            chain.append(QPixmap.fromImage(img))
        self._mips[key] = chain
        return chain

    def _draw(self, p: QPainter, kind: str, cx: float, floor: float, h: float,
              color: QColor) -> None:
        if self._sources[kind].isNull() or h <= 0:
            return
        w = h * FIGURE_ASPECT
        need = h * self.devicePixelRatioF()
        chain = self._mip_chain(kind, color)
        pix = chain[0]
        for candidate in chain:
            if candidate.height() >= need:
                pix = candidate
            else:
                break
        p.drawPixmap(QRectF(cx - w / 2, floor - h, w, h), pix, QRectF(pix.rect()))

    def _font(self, px: float, bold: bool = False) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(max(8, round(px * text_scale())))
        f.setBold(bold)
        return f

    def paintEvent(self, _event):  # noqa: N802
        c = colors()
        s = text_scale()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        w = float(self.width())
        floor = self.floor_y()
        cx = self.figure_x()
        h_now, h_target = self.heights_px()
        has_now = self._now.cm is not None
        has_target = self._target.cm is not None

        # the floor: structure, so the dim green, never the accent
        p.setPen(QPen(QColor(c["green_mid"]), 1))
        p.drawLine(QPointF(self.axis_x() + 14 * s, floor), QPointF(w - 4, floor))

        accent = QColor(c["accent"])
        shadow = QColor(accent)
        shadow.setAlphaF(SHADOW_ALPHA)
        ghost = QColor(c["muted"])
        ghost.setAlphaF(GHOST_ALPHA)
        lines = _mix(ghost, accent, self._known)

        self._head_guides(p, c, s, h_now, h_target, cx)
        # behind: where you're going; in front: where you are. The lines get
        # a thin halo in the card colour, so they stay readable on the shadow.
        halo = QColor(c["card"])
        d_now, d_target = self.drawn_px(h_now), self.drawn_px(h_target)
        if has_target:
            self._draw(p, "fill", cx, floor, d_target, shadow)
        if has_now:
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                self._draw(p, "lines", cx + dx, floor + dy, d_now, halo)
            solid = solid_amount(d_now)
            if solid > 0.0:
                # thin lines at this size vanish on the shadow
                bright = QColor(lines)
                bright.setAlphaF(lines.alphaF() * solid)
                self._draw(p, "fill", cx, floor, d_now, bright)
            self._draw(p, "lines", cx, floor, d_now, lines)
        self._eye_lines(p, c, s, h_now if has_now else 0.0, h_target if has_target else 0.0)
        tags = self._readouts()
        self._draw_scale(p, c, s, [y for y, _t, _s in tags])
        for y, text, strong in tags:
            self._readout(p, c, s, y, text, strong)
        p.end()

    def _head_guides(self, p: QPainter, c: dict, s: float, h_now: float, h_target: float,
                     cx: float) -> None:
        """A hairline from the scale to each head at her eye line, and on
        past it on the other side — never through her face (_eye_lines
        crosses it, faintly): faint at rest, bright while it is held or
        hovered. It is at the height at once, like the ring and the pointer
        (and the gap where her head will be): only she eases into it. Over
        the scale, a light dashed line where the mouse would pick the
        target. (Their heights: _readouts.)"""
        ax, floor = self.axis_x(), self.floor_y()
        for which, alpha in (("target", 0.22), ("now", 0.45)):
            v = self._shown(which)
            if v is None:
                continue
            y = self.y_of(v)
            h = floor - y                      # her eye height once she is there
            head_l, head_r = self._head_edges(h)
            active = self._active(which)
            guide = QColor(c["accent"])
            guide.setAlphaF(1.0 if active else alpha)
            p.setPen(QPen(guide, 1.4 if active else 1.0))
            if head_l - 3 * s > ax:
                p.drawLine(QPointF(ax, y), QPointF(head_l - 3 * s, y))
            end = self.figure_rect(h).right() + 4 * s
            if end > head_r + 3 * s:
                p.drawLine(QPointF(head_r + 3 * s, y), QPointF(end, y))
        if self._hover_cm is not None and self._drag is None:
            y = self.y_of(self._hover_cm)
            guide = QColor(c["accent"])
            guide.setAlphaF(0.5)
            p.setPen(QPen(guide, 1.0, Qt.DashLine))
            reach = self.drawn_px(max(h_now, h_target, floor - y)) * FIGURE_ASPECT / 2
            p.drawLine(QPointF(ax + 6 * s, y), QPointF(cx + reach + 4 * s, y))

    def _eye_lines(self, p: QPainter, c: dict, s: float, h_now: float,
                   h_target: float) -> None:
        """Across each head at her eye line: a small grey dotted line, over
        the figure, where the height line would cut through her face."""
        floor = self.floor_y()
        for which, h in (("target", h_target), ("now", h_now)):
            if h <= 0 or self._shown(which) is None:
                continue
            left, right = self._head_edges(h)
            if right - left < 6 * s:
                continue                       # a head this small needs no line
            grey = QColor(c["muted"])
            grey.setAlphaF(0.85 if self._active(which) else 0.5)
            p.setPen(QPen(grey, 1.0, Qt.DotLine))
            p.drawLine(QPointF(left, floor - h), QPointF(right, floor - h))

    def _active(self, which: str) -> bool:
        """NOW's or the target's head line is lit: held, or under the mouse."""
        if which == "target":
            return self._drag == "target" or self._hover == "target"
        return self._hover in ("now", ("head", "now"))

    def _readouts(self) -> List[Tuple[float, str, bool]]:
        """(y, text, strong) for each height tag to show: a lit head line's,
        or the one under the mouse on the scale. They sit on the scale's
        label side, over its numbers — a slider's readout, so no room is
        kept for them beside her — and, like its handles, at the height at
        once: never trailing the eased figure."""
        tags = []
        for which in ("target", "now"):
            v = self._shown(which)
            if v is not None and self._active(which):
                tags.append((self.y_of(v), format_height(v), which == "target"))
        if self._hover_cm is not None and self._drag is None:
            tags.append((self.y_of(self._hover_cm), format_height(self._hover_cm), False))
        return tags

    def _readout(self, p: QPainter, c: dict, s: float, y: float, text: str,
                 strong: bool) -> None:
        p.setFont(self._font(13, bold=True))
        tw = p.fontMetrics().horizontalAdvance(text)
        right = self.axis_x() - 10 * s
        box = QRectF(right - tw - 12 * s, y - 11 * s, tw + 12 * s, 22 * s)
        if box.left() < 1:
            box.moveLeft(1)
        p.setPen(QPen(QColor(c["accent"] if strong else c["line"]), 1))
        p.setBrush(QColor(c["card"]))
        p.drawRoundedRect(box, 4 * s, 4 * s)
        p.setPen(QColor(c["txt"] if strong else c["muted"]))
        p.drawText(box, Qt.AlignCenter, text)

    def _draw_scale(self, p: QPainter, c: dict, s: float, tag_ys=()) -> None:
        ax = self.axis_x()
        y_top, y_bot = self.y_of(self._hi), self.y_of(self._lo)
        p.setPen(QPen(QColor(c["line"]), 2.0 * s, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(ax, y_bot), QPointF(ax, y_top))
        # the powers of ten, dim; the two ends are the range's min and max
        p.setFont(self._font(12))
        for v in scale_decades(self._lo, self._hi):
            y = self.y_of(v)
            p.setPen(QPen(QColor(c["green_mid"]), 1))
            p.drawLine(QPointF(ax - 5 * s, y), QPointF(ax, y))
            # not under MIN / MAX, nor half-hidden under a height tag
            if abs(y - y_top) > 16 * s and abs(y - y_bot) > 16 * s \
                    and all(abs(y - ty) > 19 * s for ty in tag_ys):
                p.setPen(QColor(c["dim"]))
                p.drawText(QRectF(ax - 86 * s, y - 9 * s, 78 * s, 18 * s),
                           Qt.AlignRight | Qt.AlignVCenter, decade_label(v))
        for y, value, word, which in ((y_top, self._hi, "MAX", "hi"),
                                      (y_bot, self._lo, "MIN", "lo")):
            p.setPen(QPen(QColor(c["line"]), 2.0 * s, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(ax - 7 * s, y), QPointF(ax + 7 * s, y))
            if self._editing == which:
                continue                       # the field sits there now
            hover = self._hover == ("end", which)
            p.setFont(self._font(14, bold=True))
            p.setPen(QColor(c["accent"] if hover else c["muted"]))
            text = format_height(value)
            p.drawText(QRectF(ax - 12 * s - 120 * s, y - 10 * s, 120 * s, 20 * s),
                       Qt.AlignRight | Qt.AlignVCenter, text)
            tw = p.fontMetrics().horizontalAdvance(text)
            if hover:                          # it is a field: click to type
                p.setPen(QPen(QColor(c["accent"]), 1))
                p.drawLine(QPointF(ax - 12 * s - tw, y + 10 * s),
                           QPointF(ax - 12 * s, y + 10 * s))
            note = "LIMIT" if word == "MAX" and self._hi >= self._limit else word
            p.setFont(self._font(10, bold=True))
            p.setPen(QColor(c["dim"]))
            wy = y - 18 * s if which == "hi" else y + 17 * s      # above MAX, below MIN
            p.drawText(QRectF(ax - 12 * s - 120 * s, wy - 7 * s, 120 * s, 14 * s),
                       Qt.AlignRight | Qt.AlignVCenter, note)
        # the saved heights: numbered marks on the scale, like a door frame
        p.setFont(self._font(10, bold=True))
        for n, v in sorted(self._saved.items()):
            if v is None or not self._lo <= v <= self._hi:
                continue
            y = self.y_of(v)
            ok = self._mark_ok.get(n, (False, ""))[0]
            hover = self._hover == ("mark", n) and ok
            r = (MARK_PX + (1.5 if hover else 0.0)) * s
            p.setPen(QPen(QColor(c["card"]), 2))
            p.setBrush(QColor(c["accent"] if hover else (c["green"] if ok else c["green_mid"])))
            p.drawEllipse(QPointF(ax, y), r, r)
            p.setPen(QColor(c["ink"] if ok else c["dim"]))
            p.drawText(QRectF(ax - r, y - r, 2 * r, 2 * r), Qt.AlignCenter, str(n))
        self._draw_target_handle(p, c, s, ax)
        self._draw_now_handle(p, c, s, ax)

    def _draw_target_handle(self, p: QPainter, c: dict, s: float, ax: float) -> None:
        v = self._shown("target")
        if v is None:
            return
        y = self.y_of(v)
        active = (self._drag == "target" or self._hover == "target") and not self._target_locked
        fill = QColor(c["accent"])
        fill.setAlphaF(0.18 if self._target_locked else (0.6 if active else SHADOW_ALPHA + 0.12))
        tip = ax + POINTER_DX * s
        p.setPen(QPen(QColor(c["accent"] if active else
                             (c["green_mid"] if self._target_locked else c["line"])), 1.2))
        p.setBrush(fill)
        p.drawPolygon(QPolygonF([QPointF(tip, y), QPointF(tip + 13 * s, y - 8 * s),
                                 QPointF(tip + 13 * s, y + 8 * s)]))

    def _draw_now_handle(self, p: QPainter, c: dict, s: float, ax: float) -> None:
        """The ring at your height. It only shows: nothing on the scale sends."""
        v = self._shown("now")
        if v is None:
            return
        y = self.y_of(v)
        p.setPen(QPen(QColor(c["accent"]), 2.4 * s))
        # hollow: a saved height under it stays readable (you are at it)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(ax, y), RING_PX * s, RING_PX * s)


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = min(1.0, max(0.0, t))
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * t,
                           a.greenF() + (b.greenF() - a.greenF()) * t,
                           a.blueF() + (b.blueF() - a.blueF()) * t,
                           a.alphaF() + (b.alphaF() - a.alphaF()) * t)
