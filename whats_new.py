"""What changed — told once, to someone who just updated (OscGoesPurrr's
"What's new", the same design).

After an update the app opens a small "What's new" window at launch: a few
lines per release, one release per page (Back / Next when an update skipped
several, so none of their news is lost), and where a change has a home in
the app, a "Take me there" button that opens it and lights it up. Settings
→ Updates → What's new opens it again, with every release this build has.

This module is the content and the rule for when it shows; the window is
ui/whats_new.py, the launch hook controller.whats_new_on_launch.

Adding a release: put a new entry at the TOP of RELEASES, under the version
it ships as (version.py: 2.0.<commits on main>). Keep it to what a user
would notice — CHANGELOG.md has the full list. An item's `target` names a
place the window can open (ui/window.py PLACES; a test fails on one that
does not exist); its `icon` is one of the VRChat menu's icons
(assets/menu/<icon>.png) or "" for none.

Pure data and one rule: no Qt, no settings, no I/O.
"""

from __future__ import annotations

from typing import List, NamedTuple, Tuple

from updater import parse_version

# The setting that remembers the newest version whose notes were shown.
SEEN_KEY = "whats_new_seen_version"


class Item(NamedTuple):
    title: str
    text: str
    target: str = ""        # "" = nothing to open
    icon: str = ""          # assets/menu/<icon>.png; "" = none


class Release(NamedTuple):
    version: str
    items: Tuple[Item, ...]


RELEASES: Tuple[Release, ...] = (
    Release("2.0.36", (
        Item("Size parameters",
             "Let your avatar change your size: a contact, a toggle or a radial grows or "
             "shrinks you while it's on, each card at its own speed. Type a parameter's "
             "name on a card, or Pick… it from the avatar's list beside the window.",
             "size_params", icon="grow"),
        Item("🎲 Random height",
             "A card that picks a height between two — on its 🎲, the VRChat menu's Random "
             "height, or when a parameter turns on.",
             "size_params", icon="roll"),
        Item("Nine saved heights, on the numpad",
             "Numpad 1–9 do what a click on saved height 1–9 does. Change the keys in "
             "Settings → Grow & shrink while held.",
             "slots", icon="saved"),
        Item("Back to your height in VR",
             "Both fists and a jump puts you back at the avatar's own height — or the "
             "gesture you set in Settings.",
             "vr_gesture", icon="own_height"),
        Item("More in the VRChat menu",
             "Own height, Random height and Pause cards; and contact examples in the "
             "VRCFury package that drive the Grow and Shrink cards.",
             "menu_guide", icon="pause_cards"),
        Item("Back to your own height",
             "The ↺ Own height button top right of NOW — or numpad * (your own key in Settings "
             "→ Grow & shrink while held) — puts you back at the avatar's own height, the "
             "one it has before any scaling.",
             "own_height", icon="load1"),
        Item("Lighter in the background",
             "About a third of the CPU it used while idle: it reads only what it needs "
             "from VRChat and draws less when you're not looking.",
             "", icon=""),
        Item("On Linux too",
             "Every release now has a Linux AppImage next to the Windows exe, and it "
             "updates itself the same way.",
             "updates", icon=""),
    )),
    Release("2.0.26", (
        Item("Six saved heights",
             "Two more slots, three across in the Height panel.",
             "slots", icon="saved"),
        Item("One click to go",
             "Each saved height can go there at once (pink) or start the timed "
             "transition (yellow) instead of only becoming the target: open Settings "
             "and use the ▾ on it, or right-click it. A pink 1 cm slot is one click "
             "from 1 cm.",
             "slot_actions", icon="load1"),
        Item("The same for the scale",
             "The button on top of the picture says what a click on the scale "
             "does: Select height, Go instant or Go timed.",
             "scale_mode", icon="play_pause"),
        Item("Nudges stop at the limit",
             "−100 at 85 cm goes straight to 1 cm, and −1 at 2 cm reaches 1 cm.",
             "", icon="shrink"),
        Item("Exact at the edges",
             "Go timed starts from 1 cm, and heights in metres show to the millimetre "
             "(12.345 m) — VRChat's rounding no longer gets in the way.",
             "", icon=""),
    )),
    Release("2.0.23", (
        Item("Number fields work again",
             "The target, the transition's time and the other number fields were "
             "empty and couldn't be typed in. Fixed — sorry about that.",
             "", icon=""),
    )),
    Release("2.0.20", (
        Item("Your height and the target on one picture",
             "Two copies of one figure on a height scale from 1 cm to 100 m, eyes "
             "at the height, with the ratio written out. Click or drag the scale "
             "to pick a target.",
             "scale_mode", icon="menu"),
        Item("Go instant or Go timed",
             "Go there at once, or grow into it over seconds, minutes or hours, at "
             "even speed or even growth.",
             "", icon="play_pause"),
        Item("A menu in VRChat",
             "Grow, Shrink, Play / Pause, Stop and your saved heights from the "
             "Action Menu — a VRCFury prefab for your avatar.",
             "menu_guide", icon="grow"),
        Item("Hold to grow",
             "Hold numpad + or − in VRChat to grow or shrink smoothly.",
             "settings_height", icon="grow"),
        Item("Updates itself",
             "A newer version shows up as an orange chip at the top: one click "
             "installs it.",
             "updates", icon=""),
    )),
)


def _version(text) -> tuple:
    return parse_version(text) or ()


def _is_after(a: str, b: str) -> bool:
    """`a` is a later version than `b`. Junk on the right is "before
    everything"; junk on the left is never later."""
    va, vb = _version(a), _version(b)
    if not va:
        return False
    if not vb:
        return True
    width = max(len(va), len(vb))
    return va + (0,) * (width - len(va)) > vb + (0,) * (width - len(vb))


def releases_for(current: str) -> List[Release]:
    """Every release this build has notes for, newest first — what the
    "What's new" button pages through. Never a version later than this
    build."""
    return [r for r in RELEASES if not _is_after(r.version, current)]


def unseen_releases(seen: str, current: str) -> List[Release]:
    """What to show at launch: every release later than the last one whose
    notes were shown (`seen`, "" for never) and not later than this build,
    newest first — all of them, so someone who skipped a few updates pages
    through each one's news. Empty when there is nothing new to tell."""
    return [r for r in releases_for(current) if _is_after(r.version, seen)]


def as_plain(releases) -> list:
    """Releases as plain lists and tuples, for the window:
    [(version, [(title, text, target, icon), ...]), ...]."""
    return [(r.version, [(i.title, i.text, i.target, i.icon) for i in r.items])
            for r in releases]
