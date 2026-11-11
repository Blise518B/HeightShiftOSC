"""Pure height logic for HeightShift — no Qt, no network.

Everything that decides WHAT gets written to VRChat lives here so it can be
unit-tested on its own (tests/test_height_logic.py):

  * check_write()        — the one gate every outgoing height passes
  * reported_cm()        — what counts as a usable height read from VRChat
  * ReportGate           — keeps echoes of our own sends from becoming the
                           base of the next relative step
  * HeightHistory        — which height to restore after an avatar change
  * Transition           — the slow transition's clock and curve
  * scale_fraction/scale_height — the logarithmic height scale beside the figure
  * MenuInput            — the in-VRChat menu's buttons, as VRChat reports them

The one rule behind all of it: what the app READS is never changed (no
clamping, no rounding) — the avatar's real height is the truth — and what it
WRITES is checked, never silently clamped into something else.
"""

from __future__ import annotations

import math
import re
from collections import deque
from typing import Deque, Dict, Optional, Tuple

from constants import (
    CLICK_ACTIONS,
    DEFAULT_RANDOM_GO,
    DEFAULT_RANDOM_MAX_CM,
    DEFAULT_RANDOM_MIN_CM,
    DEFAULT_SIZE_PARAM_SPEED,
    DEFAULT_SIZE_PARAM_UNIT,
    ECHO_HOLD_S,
    HOTKEY_SPEED_MAX_CM,
    HOTKEY_SPEED_MAX_PCT,
    HOTKEY_SPEED_MIN,
    MAX_HEIGHT_CM,
    MENU_AVATAR_GUARD_S,
    MENU_DEBOUNCE_S,
    MENU_GROW,
    MENU_LOAD,
    MENU_PLAY,
    MENU_RESET,
    MENU_ROLL,
    MENU_SAVE,
    MENU_SHRINK,
    MENU_STOP,
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


# How far a height may sit past a limit and still count as at it: the
# rounding of a 32-bit float near 1 cm (VRChat sends metres as float32).
FLOAT_SLACK_CM = 1e-4


def max_height_cm(unlocked: bool) -> float:
    return float(UNLOCKED_MAX_HEIGHT_CM if unlocked else MAX_HEIGHT_CM)


def check_write(cm, unlocked: bool) -> Optional[str]:
    """None when `cm` may be sent to VRChat, otherwise why it may not.

    Never clamps: a value outside the limits is refused, so a typo can't turn
    into a different height that nobody asked for.
    """
    if not is_number(cm):
        return "not a number"
    # OSC carries metres as 32-bit floats: VRChat's "1 cm" arrives as
    # 0.99999998 cm. A height within that rounding of a limit IS the limit
    # (else, at 1 cm, Go timed refused "the current height is below 1 cm").
    slack = max(FLOAT_SLACK_CM, abs(cm) * 1e-6)
    if cm < MIN_HEIGHT_CM - slack:
        return f"below the {format_height(MIN_HEIGHT_CM)} minimum"
    top = max_height_cm(unlocked)
    if cm > top + slack:
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


def default_height_cm(current_cm: Optional[float], scale_factor: Optional[float]) -> Optional[float]:
    """The avatar's own (default) eye height: VRChat's ScaleFactor is the
    current eye height over the default one. None when either is unknown
    or unusable."""
    if not (is_number(current_cm) and is_number(scale_factor)):
        return None
    if current_cm <= 0 or scale_factor <= 0:
        return None
    return current_cm / scale_factor


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
    # The unit follows the ROUNDED value (999.96 cm is "10 m", never
    # "1,000 cm"), and every unit shows down to the millimetre the app keeps
    # (12.345 m, not 12.35 m — typed back, that would be 5 mm off).
    if round(cm / 100, 3) >= 1_000:
        return f"{_trim(cm / 100_000, 3)} km"
    if round(cm, 1) >= 1_000:
        return f"{_trim(cm / 100, 3)} m"
    return f"{_trim(cm, 1)} cm"


_HEIGHT_TEXT = re.compile(r"(\d+(?:\.\d*)?|\.\d+)(cm|m|km)?")
_UNIT_CM = {"cm": 1.0, "m": 100.0, "km": 100_000.0}


def parse_height(text: str) -> Optional[float]:
    """A typed height in cm, or None: "170", "170 cm", "1.7 m", "1,7 m"
    (a decimal comma too), "1.25 km". A bare number is cm. "1,234.5 cm"
    reads the comma as a thousands mark, since it has a point as well."""
    t = re.sub(r"\s+", "", str(text)).lower()
    if "," in t and "." in t:
        t = t.replace(",", "")
    else:
        t = t.replace(",", ".")
    m = _HEIGHT_TEXT.fullmatch(t)
    if m is None:
        return None
    return float(m.group(1)) * _UNIT_CM[m.group(2) or "cm"]


def format_height_alt(cm: float) -> str:
    """The same height in the other unit, for the line under the big number
    (the other one than format_height picked, decided the same way)."""
    if format_height(cm).endswith(" cm"):
        return f"{_trim(cm / 100, 3)} m"
    return f"{_trim(cm, 1)} cm"


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
# Hold-to-grow hotkeys
# ----------------------------------------------------------------------

SPEED_PERCENT = "pct"   # the same share of the height every second (looks even)
SPEED_CM = "cm"         # the same number of cm every second
SPEED_UNITS = (SPEED_PERCENT, SPEED_CM)


def speed_text(speed: float, unit: str, direction: int = 0) -> str:
    """5 cm/s, 2.5 %/s; with a direction, signed: +5 cm/s, −2.5 %/s."""
    sign = "" if not direction else ("+" if direction > 0 else "−")
    return f"{sign}{speed:.3g} {'cm' if unit == SPEED_CM else '%'}/s"


def hold_height(base_cm: float, seconds: float, speed: float, unit: str,
                direction: int) -> float:
    """The height after holding the grow (+1) or shrink (-1) key for
    `seconds`, starting from `base_cm`. Computed from the start of the hold,
    never step by step, so no rounding piles up however long it is held.

    Percent shrinks by dividing, so growing and then shrinking for the same
    time lands back where it started. Not bounded here: the caller keeps it
    inside the limits."""
    t = max(0.0, float(seconds))
    if unit == SPEED_CM:
        return base_cm + direction * speed * t
    factor = (1.0 + speed / 100.0) ** t
    return base_cm * factor if direction > 0 else base_cm / factor


# ----------------------------------------------------------------------
# Size parameters: avatar parameters that grow or shrink you
# ----------------------------------------------------------------------

PARAM_GROW, PARAM_SHRINK = "grow", "shrink"
KIND_PARAM, KIND_RANDOM = "param", "random"     # a parameter card, a random card
PARAM_TYPES = ("Bool", "Int", "Float")
_OSC_TYPES = {"T": "Bool", "F": "Bool", "i": "Int", "f": "Float"}


def param_type(tag) -> Optional[str]:
    """An OSCQuery TYPE ("T", "F", "i", "f") as the picker shows it, or None
    for a kind a size parameter can't use (a string, a vector)."""
    return _OSC_TYPES.get(tag[:1]) if isinstance(tag, str) and len(tag) == 1 else None


def param_level(value) -> float:
    """How hard an avatar parameter pushes, 0..1: a Bool on = 1, an Int not
    0 = 1, a Float its own value (VRChat's run -1..1: below 0 is off)."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int):
        return 1.0 if value != 0 else 0.0
    if is_number(value):
        return min(1.0, max(0.0, float(value)))
    return 0.0


def drive_height(cm: float, seconds: float, terms) -> float:
    """The height after `seconds` of size parameters pushing from `cm`.

    `terms`: (direction +1/-1, speed, unit, level 0..1) per parameter. A
    level is that share of the speed: 0.5 of 10 cm/s is 5 cm/s, 0.5 of
    10 %/s is 5 %/s. Percent terms multiply (shrinking divides, as
    hold_height), cm terms add, so growing and shrinking at the same speed
    hold the height still. Not bounded here: the caller keeps it inside the
    limits."""
    t = max(0.0, float(seconds))
    log_factor = 0.0
    add = 0.0
    for direction, speed, unit, level in terms:
        rate = float(speed) * max(0.0, min(1.0, float(level)))
        if rate <= 0.0:
            continue
        if unit == SPEED_CM:
            add += direction * rate * t
        else:
            log_factor += direction * math.log1p(rate / 100.0) * t
    return cm * math.exp(log_factor) + add


def clean_size_param(raw) -> Optional[Dict[str, object]]:
    """A size parameter from the config, checked: None when it isn't one.
    An empty `param` is a card still waiting for its parameter."""
    if not isinstance(raw, dict):
        return None
    param = raw.get("param", "")
    if not isinstance(param, str):
        return None
    param = param.strip()
    if param.startswith("/avatar/parameters/"):
        param = param[len("/avatar/parameters/"):]
    unit = raw.get("unit") if raw.get("unit") in SPEED_UNITS else DEFAULT_SIZE_PARAM_UNIT
    top = speed_max(unit)
    speed = raw.get("speed", DEFAULT_SIZE_PARAM_SPEED)
    if not is_number(speed) or not HOTKEY_SPEED_MIN <= speed <= top:
        speed = min(top, DEFAULT_SIZE_PARAM_SPEED)
    ptype = raw.get("type") if raw.get("type") in PARAM_TYPES else ""
    on = raw.get("on") if isinstance(raw.get("on"), bool) else True
    if raw.get("kind") == KIND_RANDOM:
        lo, hi = raw.get("min"), raw.get("max")
        lo = float(lo) if is_number(lo) and lo >= MIN_HEIGHT_CM else DEFAULT_RANDOM_MIN_CM
        hi = float(hi) if is_number(hi) and hi >= MIN_HEIGHT_CM else DEFAULT_RANDOM_MAX_CM
        lo, hi = min(lo, UNLOCKED_MAX_HEIGHT_CM), min(hi, UNLOCKED_MAX_HEIGHT_CM)
        go = raw.get("go") if raw.get("go") in CLICK_ACTIONS else DEFAULT_RANDOM_GO
        return {"kind": KIND_RANDOM, "param": param, "type": ptype,
                "min": min(lo, hi), "max": max(lo, hi), "go": go, "on": on}
    return {
        "kind": KIND_PARAM,
        "param": param,
        "type": ptype,
        "dir": raw.get("dir") if raw.get("dir") in (PARAM_GROW, PARAM_SHRINK) else PARAM_GROW,
        "speed": float(speed),
        "unit": unit,
        "on": on,
    }


def random_height(lo_cm: float, hi_cm: float, rnd: float) -> float:
    """A height between `lo_cm` and `hi_cm` for `rnd` in [0, 1): even on the
    height scale (log), so 1–10 m is as likely as 10–100 m, like the scale
    beside the figure. Whole centimetres (0.1 cm below 10 cm)."""
    lo, hi = sorted((max(float(MIN_HEIGHT_CM), lo_cm), max(float(MIN_HEIGHT_CM), hi_cm)))
    cm = math.exp(math.log(lo) + (math.log(hi) - math.log(lo)) * min(1.0, max(0.0, rnd)))
    cm = round(cm, 1) if cm < 10 else float(round(cm))
    return min(hi, max(lo, cm))


def gestures_match(left, right, want_left: int, want_right: int) -> bool:
    """Each hand shows its gesture (VRChat's GestureLeft / GestureRight:
    0 neutral, 1 fist, … 7 thumbs up)."""
    return (is_number(left) and int(left) == want_left
            and is_number(right) and int(right) == want_right)


def vr_reset_gesture(left, right, grounded_before, grounded_now,
                     want_left: int = 1, want_right: int = 1) -> bool:
    """The two gestures shown as the feet leave the ground (Grounded: on ->
    off): the jump of "both fists + jump", back to the avatar's own height."""
    return (gestures_match(left, right, want_left, want_right)
            and grounded_before is not None
            and param_level(grounded_before) > 0 and param_level(grounded_now) <= 0)


def param_rose(old, new) -> bool:
    """A parameter turned on: from a known off to on (a contact touched, a
    button pressed) — not a first value after an avatar load."""
    return old is not None and param_level(old) <= 0.0 < param_level(new)


def speed_max(unit: str) -> float:
    """The fastest a hold or a size parameter may go, in `unit`."""
    return HOTKEY_SPEED_MAX_CM if unit == SPEED_CM else HOTKEY_SPEED_MAX_PCT


def flatten_parameters(node, out: Optional[Dict[str, Tuple[str, object]]] = None
                       ) -> Dict[str, Tuple[str, object]]:
    """VRChat's OSCQuery tree under /avatar/parameters -> {name: (type,
    value)}, the names as the avatar has them (`/avatar/parameters/`
    dropped; a name with a `/` in it is a node inside a node). Kinds a size
    parameter can't use are left out."""
    if out is None:
        out = {}
    if not isinstance(node, dict):
        return out
    contents = node.get("CONTENTS")
    if isinstance(contents, dict) and contents:
        for child in contents.values():
            flatten_parameters(child, out)
        return out
    path = node.get("FULL_PATH")
    kind = param_type(node.get("TYPE"))
    if not isinstance(path, str) or kind is None:
        return out
    prefix = "/avatar/parameters/"
    if not path.startswith(prefix) or len(path) == len(prefix):
        return out
    value = node.get("VALUE")
    value = value[0] if isinstance(value, list) and value else None
    if kind == "Bool" and not isinstance(value, bool):
        value = node.get("TYPE") == "T" if value is None else bool(value)
    out[path[len(prefix):]] = (kind, value)
    return out


# ----------------------------------------------------------------------
# The height scale (logarithmic)
# ----------------------------------------------------------------------
# The scale beside the figure is the height slider. 1 cm .. 100 m is four
# decades (unlocked, 1000 m: five); on a log scale each decade gets the same room, so
# 170 cm is as easy to hit as 17 m. Its ends are the slider range.


def _scale_bounds(lo: float, hi: float) -> Tuple[float, float]:
    lo = max(float(MIN_HEIGHT_CM), float(lo))
    hi = max(lo + 1.0, float(hi))
    return lo, hi


def scale_fraction(cm: float, lo: float, hi: float) -> float:
    """Where `cm` sits on the scale: 0 at `lo`, 1 at `hi`, pinned to the ends."""
    lo, hi = _scale_bounds(lo, hi)
    cm = min(hi, max(lo, float(cm)))
    return (math.log(cm) - math.log(lo)) / (math.log(hi) - math.log(lo))


def tidy_height(cm: float, digits: int = 3) -> float:
    """A dragged height to three significant digits (2.3456 m -> 2.35 m), so
    what gets set reads as it was meant."""
    if not is_number(cm) or cm <= 0:
        return cm
    return round(float(cm), digits - 1 - math.floor(math.log10(cm)))


def scale_height(fraction: float, lo: float, hi: float) -> float:
    """The height at a place on the scale: exactly `lo` and `hi` at the ends,
    tidied in between (and never outside them)."""
    lo, hi = _scale_bounds(lo, hi)
    f = min(1.0, max(0.0, float(fraction)))
    if f <= 0.0:
        return lo
    if f >= 1.0:
        return hi
    value = math.exp(math.log(lo) + f * (math.log(hi) - math.log(lo)))
    return float(min(hi, max(lo, tidy_height(value))))


def check_range(lo, hi, unlocked: bool) -> Optional[str]:
    """None when the height scale may run from `lo` to `hi` (its MIN and
    MAX), otherwise why not. Never clamps, like check_write."""
    if not (is_number(lo) and is_number(hi)):
        return "not a height"
    if lo < MIN_HEIGHT_CM:
        return f"the bottom is below the {format_height(MIN_HEIGHT_CM)} minimum"
    top = max_height_cm(unlocked)
    if hi > top:
        if unlocked:
            return f"the top is above the {format_height(top)} maximum"
        return (f"the top is above the {format_height(top)} limit "
                "(tick “Unlock upper limit” to go higher)")
    if lo >= hi:
        return "the bottom has to be below the top"
    return None


def scale_decades(lo: float, hi: float):
    """The powers of ten inside the range, for the scale's ticks."""
    lo, hi = _scale_bounds(lo, hi)
    out, e = [], math.floor(math.log10(lo))
    while 10.0 ** e <= hi * 1.0001:
        if 10.0 ** e >= lo * 0.9999:
            out.append(float(10.0 ** e))
        e += 1
    return out


# ----------------------------------------------------------------------
# The in-VRChat menu
# ----------------------------------------------------------------------

MENU_KINDS = {MENU_GROW: "grow", MENU_SHRINK: "shrink", MENU_PLAY: "play",
              MENU_STOP: "stop", MENU_LOAD: "load", MENU_SAVE: "save",
              MENU_RESET: "reset", MENU_ROLL: "roll"}
MENU_HELD = ("grow", "shrink")


def _menu_level(value) -> Optional[int]:
    """A menu parameter's value as an int: Bools 0 / 1, Ints as they are."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return int(round(value))
    return None


class MenuInput:
    """Turns the HeightShift menu's avatar parameters, as VRChat reports
    them, into what the app should do.

    A Button in VRChat's menu sets its parameter while it is held and puts
    it back to 0 when let go, so:
      * Grow and Shrink are held: `held` says which are down right now, and
        offer() reports each going down or up ("grow", 1) / ("grow", 0).
      * Play, Stop, Own height, Random height, Load N and Save N act once,
        when pressed: ("play", 0), ("stop", 0), ("reset", 0), ("roll", 0),
        ("load", N), ("save", N).
    (Pause cards is a Toggle: the controller reads its value, not presses.)

    Two kinds of report are not presses and are dropped:
      * anything within `guard_s` of an avatar change: VRChat reports every
        parameter while the new avatar loads (the menu's are unsaved, so
        they should read 0, but a stale 1 must never act);
      * a press within `debounce_s` of the same button's release: with the
        518 router on, every packet arrives twice, and the second copy of a
        quick tap can land after its release.
    A release always counts, so a held button can never get stuck.
    """

    def __init__(self, guard_s: float = MENU_AVATAR_GUARD_S,
                 debounce_s: float = MENU_DEBOUNCE_S):
        self.guard_s = guard_s
        self.debounce_s = debounce_s
        self._values: Dict[str, int] = {}
        self._released_at: Dict[str, float] = {}
        self._quiet_until = -math.inf
        self.held = {kind: False for kind in MENU_HELD}

    def reset(self) -> None:
        """VRChat went away: nothing is held any more."""
        self._values.clear()
        self._released_at.clear()
        self.held = {kind: False for kind in MENU_HELD}

    def on_avatar_change(self, at: float) -> None:
        """The menu closes with the old avatar and its parameters reset."""
        self.reset()
        self._quiet_until = at + self.guard_s

    def offer(self, name: str, value, seen_at: float) -> Optional[Tuple[str, int]]:
        kind = MENU_KINDS.get(name)
        level = _menu_level(value)
        if kind is None or level is None:
            return None
        old = self._values.get(name, 0)
        self._values[name] = level
        if level == old:
            return None                       # a repeat (the router's copy)
        if level == 0:
            self._released_at[name] = seen_at
            if kind in MENU_HELD:
                self.held[kind] = False
                return kind, 0
            return None
        # a press (for Load / Save also 2 -> 3 straight away)
        if seen_at < self._quiet_until:
            return None
        if seen_at - self._released_at.get(name, -math.inf) < self.debounce_s:
            return None
        if kind in MENU_HELD:
            self.held[kind] = True
            return kind, 1
        if kind in ("load", "save"):
            return kind, level
        return kind, 0
