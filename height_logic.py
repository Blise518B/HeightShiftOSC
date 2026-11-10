"""Pure height logic for HeightShift — no Qt, no network.

Everything that decides WHAT gets written to VRChat lives here so it can be
unit-tested on its own (tests/test_height_logic.py):

  * check_write()        — the one gate every outgoing height passes
  * reported_cm()        — what counts as a usable height read from VRChat
  * ReportGate           — keeps echoes of our own sends from becoming the
                           base of the next relative step
  * HeightHistory        — which height to restore after an avatar change
  * Transition           — the slow transition's clock and curve
  * slider_pos/slider_cm — the logarithmic slider mapping

The one rule behind all of it: what the app READS is never changed (no
clamping, no rounding) — the avatar's real height is the truth — and what it
WRITES is checked, never silently clamped into something else.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Optional, Tuple

from constants import (
    ECHO_HOLD_S,
    MAX_HEIGHT_CM,
    MIN_HEIGHT_CM,
    PRESERVE_REPORT_GUARD_S,
    UNLOCKED_MAX_HEIGHT_CM,
)

# ----------------------------------------------------------------------
# Limits and validation
# ----------------------------------------------------------------------


def is_number(value) -> bool:
    """A real, finite number (bools are not heights)."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def max_height_cm(unlocked: bool) -> float:
    return float(UNLOCKED_MAX_HEIGHT_CM if unlocked else MAX_HEIGHT_CM)


def check_write(cm, unlocked: bool) -> Optional[str]:
    """None when `cm` may be sent to VRChat, otherwise why it may not.

    Never clamps: a value outside the limits is refused, so a typo can't turn
    into a different height that nobody asked for.
    """
    if not is_number(cm):
        return "not a number"
    if cm < MIN_HEIGHT_CM:
        return f"below the {format_height(MIN_HEIGHT_CM)} minimum"
    top = max_height_cm(unlocked)
    if cm > top:
        if unlocked:
            return f"above the {format_height(top)} maximum"
        return (f"above the {format_height(top)} limit "
                "(tick “Unlock upper limit” to go higher)")
    return None


def reported_cm(meters) -> Optional[float]:
    """A height VRChat reported (metres) in cm, or None if it is not a usable
    height. Deliberately NOT clamped or rounded."""
    try:
        m = float(meters)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(m) or m <= 0:
        return None
    return m * 100.0


def same_height(a: Optional[float], b: Optional[float],
                tolerance_cm: float = 0.05) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tolerance_cm


# ----------------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------------


def _trim(value: float, decimals: int) -> str:
    text = f"{value:,.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def format_height(cm: float) -> str:
    """Human-readable height in the unit that reads best: 173.4 cm, 12.5 m,
    1.25 km."""
    if cm >= 100_000:
        return f"{_trim(cm / 100_000, 3)} km"
    if cm >= 1_000:
        return f"{_trim(cm / 100, 2)} m"
    return f"{_trim(cm, 1)} cm"


def format_height_alt(cm: float) -> str:
    """The same height in the other unit, for the line under the big number."""
    if cm >= 1_000:
        return f"{_trim(cm, 1)} cm"
    return f"{_trim(cm / 100, 3)} m"


def describe_duration(seconds: float) -> str:
    """45 s / 10 min / 1 h 30 min — for 'over …' and the graph's time axis."""
    s = max(0, int(round(seconds)))
    if s < 60:
        return f"{s} s"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} h")
    if m:
        parts.append(f"{m} min")
    if sec and not h:
        parts.append(f"{sec} s")
    return " ".join(parts)


def format_duration(seconds: float) -> str:
    """3:05 / 1:02:03 — for 'time left'."""
    s = max(0, int(math.ceil(seconds)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


# ----------------------------------------------------------------------
# Echo handling
# ----------------------------------------------------------------------


class ReportGate:
    """Decides when a height VRChat reports may become the known height.

    Every report carries the time it was SEEN: when an OSC packet arrived, or
    when an HTTP read was asked for (its answer can't be older than that).

      * Dropped: a report seen before our latest send (a stale report handled
        a moment after a +1 cm click would pull the base back down), or
        before the latest avatar change (it describes the old avatar), or
        before a report already taken (a slow HTTP answer must not replace a
        newer OSC packet).
      * Held: after every send, reports wait ECHO_HOLD_S and only the newest
        is adopted afterwards (VRChat echoes what it applied, sometimes late).

    All times come from one clock (the controller's `now`).
    """

    def __init__(self, hold_s: float = ECHO_HOLD_S):
        self.hold_s = hold_s
        self.stale_before: float = -math.inf   # latest send or avatar change
        self.hold_until: float = -math.inf
        self.newest_taken: float = -math.inf   # seen-time of the last adopted report
        self._pending: Optional[Tuple[float, float]] = None   # (seen_at, cm)

    def on_send(self, now: float) -> None:
        self.stale_before = max(self.stale_before, now)
        self.hold_until = now + self.hold_s

    def on_avatar_change(self, at: float) -> None:
        self.stale_before = max(self.stale_before, at)
        if self._pending is not None and self._pending[0] < at:
            self._pending = None

    def _is_stale(self, seen_at: float) -> bool:
        return seen_at < self.stale_before or seen_at < self.newest_taken

    def offer(self, seen_at: float, now: float, cm: float) -> Optional[float]:
        """Returns the height to adopt right now, or None (held or dropped)."""
        if self._is_stale(seen_at):
            return None
        if now < self.hold_until:
            if self._pending is None or seen_at >= self._pending[0]:
                self._pending = (seen_at, cm)
            return None
        self.newest_taken = seen_at
        return cm

    def release(self, now: float) -> Optional[float]:
        """After the hold: the newest held report (if nothing since made it
        stale), else None."""
        if now < self.hold_until or self._pending is None:
            return None
        seen_at, cm = self._pending
        self._pending = None
        if self._is_stale(seen_at):
            return None
        self.newest_taken = seen_at
        return cm

    @property
    def holding(self) -> bool:
        return self._pending is not None

    def reset(self) -> None:
        self.stale_before = -math.inf
        self.hold_until = -math.inf
        self.newest_taken = -math.inf
        self._pending = None


# ----------------------------------------------------------------------
# Which height to preserve across an avatar change
# ----------------------------------------------------------------------


class HeightHistory:
    """Recent heights with the time they were seen and where they came from
    ("vrchat" = reported by VRChat, "app" = sent by us)."""

    def __init__(self, maxlen: int = 64):
        self._items: Deque[Tuple[float, float, str]] = deque(maxlen=maxlen)

    def record(self, t: float, cm: float, source: str) -> None:
        self._items.append((t, cm, source))

    def clear(self) -> None:
        self._items.clear()

    def preserve_target(self, change_at: float,
                        guard_s: float = PRESERVE_REPORT_GUARD_S) -> Optional[float]:
        """The height the avatar had before an avatar change at `change_at`.

        Ignores everything after the change, and VRChat reports from just
        before it: VRChat can send the new avatar's default height a few ms
        BEFORE /avatar/change (see PRESERVE_REPORT_GUARD_S). Heights we sent
        ourselves are always trusted. Picks by timestamp, not by the order
        entries were recorded (an HTTP read is stamped when it was asked for,
        so it can be recorded after a newer OSC packet).
        """
        best: Optional[Tuple[float, float]] = None
        for t, cm, source in self._items:
            if t > change_at:
                continue
            if source == "vrchat" and t > change_at - guard_s:
                continue
            if best is None or t >= best[0]:
                best = (t, cm)
        return None if best is None else best[1]


# ----------------------------------------------------------------------
# Slow transition
# ----------------------------------------------------------------------

CURVE_LINEAR = "linear"   # the same number of cm every second
CURVE_SCALE = "scale"     # the same percentage every second (looks even)
CURVES = (CURVE_LINEAR, CURVE_SCALE)


def interpolate(start_cm: float, end_cm: float, fraction: float, curve: str) -> float:
    f = min(1.0, max(0.0, fraction))
    if f >= 1.0:
        return end_cm
    if curve == CURVE_SCALE and start_cm > 0 and end_cm > 0:
        return start_cm * (end_cm / start_cm) ** f
    return start_cm + (end_cm - start_cm) * f


class Transition:
    """A height change from `start_cm` to `end_cm` over `duration_s`.

    Time-based, not tick-based: the value is computed from the monotonic
    clock, so a late or skipped timer tick never shifts when the end height
    is reached. Pausing stops the clock; resuming continues from the same
    point on the curve.
    """

    def __init__(self, start_cm: float, end_cm: float, duration_s: float,
                 curve: str = CURVE_LINEAR):
        if not (is_number(start_cm) and is_number(end_cm)):
            raise ValueError("start and end must be numbers")
        if not is_number(duration_s) or duration_s <= 0:
            raise ValueError("duration must be > 0")
        self.start_cm = float(start_cm)
        self.end_cm = float(end_cm)
        self.duration_s = float(duration_s)
        self.curve = curve if curve in CURVES else CURVE_LINEAR
        self._elapsed = 0.0
        self._resumed_at: Optional[float] = None

    @property
    def playing(self) -> bool:
        return self._resumed_at is not None

    def play(self, now: float) -> None:
        if self._resumed_at is None:
            self._resumed_at = now

    def pause(self, now: float) -> None:
        if self._resumed_at is not None:
            self._elapsed += max(0.0, now - self._resumed_at)
            self._resumed_at = None

    def elapsed(self, now: float) -> float:
        running = (now - self._resumed_at) if self._resumed_at is not None else 0.0
        return min(self.duration_s, self._elapsed + max(0.0, running))

    def progress(self, now: float) -> float:
        return self.elapsed(now) / self.duration_s

    def remaining(self, now: float) -> float:
        return self.duration_s - self.elapsed(now)

    def finished(self, now: float) -> bool:
        return self.elapsed(now) >= self.duration_s

    def value_at(self, fraction: float) -> float:
        return interpolate(self.start_cm, self.end_cm, fraction, self.curve)

    def value(self, now: float) -> float:
        return self.value_at(self.progress(now))


# ----------------------------------------------------------------------
# Logarithmic slider
# ----------------------------------------------------------------------
# 1 cm .. 100 m is four decades. On a linear slider every pixel was ~30 cm;
# on a log slider each decade gets the same width, so 170 cm is as easy to
# hit as 17 m.

SLIDER_STEPS = 1000


def _slider_bounds(lo: float, hi: float) -> Tuple[float, float]:
    lo = max(float(MIN_HEIGHT_CM), float(lo))
    hi = max(lo + 1.0, float(hi))
    return lo, hi


def slider_pos(cm: float, lo: float, hi: float) -> int:
    lo, hi = _slider_bounds(lo, hi)
    cm = min(hi, max(lo, float(cm)))
    span = math.log(hi) - math.log(lo)
    return int(round((math.log(cm) - math.log(lo)) / span * SLIDER_STEPS))


def slider_cm(pos: int, lo: float, hi: float) -> float:
    """Slider position -> height, rounded to a whole centimetre (the ends
    are exactly lo and hi)."""
    lo, hi = _slider_bounds(lo, hi)
    pos = min(SLIDER_STEPS, max(0, int(pos)))
    if pos == 0:
        return lo
    if pos == SLIDER_STEPS:
        return hi
    span = math.log(hi) - math.log(lo)
    value = math.exp(math.log(lo) + span * pos / SLIDER_STEPS)
    return float(min(hi, max(lo, round(value))))
