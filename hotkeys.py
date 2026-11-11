"""Hold-to-grow hotkeys: which key is which, and whether it is held right now.

The keys have to work while VRChat has the focus, which a Qt shortcut never
would, so they are read from the system (Windows only). By POLLING the key
state (GetAsyncKeyState), not with a keyboard hook: nothing is intercepted,
every program still gets every key, typing can't be slowed down by us, and
there is nothing for an anti-cheat to object to.

"Only while VRChat is in front" is checked here too: the program behind the
foreground window, by its exe name.
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from typing import Any, Callable, Optional

MOD_CTRL, MOD_SHIFT, MOD_ALT = 1, 2, 4
_MOD_KEYS = ((MOD_CTRL, 0x11), (MOD_SHIFT, 0x10), (MOD_ALT, 0x12))   # VK_CONTROL / SHIFT / MENU

# Keys that only ever modify another one: never a hotkey on their own.
MODIFIER_VKS = frozenset({0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C,
                          0x14, 0x90, 0x91})   # + Win L/R, Caps / Num / Scroll Lock

VK_ADD, VK_SUBTRACT = 0x6B, 0x6D   # the numpad's + and -

VRCHAT_EXE = "vrchat.exe"


@dataclass(frozen=True)
class Hotkey:
    vk: int          # Windows virtual-key code
    mods: int = 0    # MOD_CTRL | MOD_SHIFT | MOD_ALT, all of them held exactly

    def to_config(self) -> dict:
        return {"vk": self.vk, "mods": self.mods}

    @staticmethod
    def from_config(value: Any) -> Optional["Hotkey"]:
        """A stored hotkey, or None when the value isn't one (hand-edited,
        another version's format): the caller falls back to the default."""
        if not isinstance(value, dict):
            return None
        vk, mods = value.get("vk"), value.get("mods", 0)
        if (not isinstance(vk, int) or isinstance(vk, bool) or not 0 < vk < 255
                or vk in MODIFIER_VKS):
            return None
        if not isinstance(mods, int) or isinstance(mods, bool) or not 0 <= mods <= 7:
            return None
        return Hotkey(vk, mods)


DEFAULT_GROW = Hotkey(VK_ADD)
DEFAULT_SHRINK = Hotkey(VK_SUBTRACT)
DEFAULT_RESET = Hotkey(0x6A)       # numpad *: back to the avatar's own height

_NAMES = {
    VK_ADD: "Num +", VK_SUBTRACT: "Num −", 0x6A: "Num *", 0x6F: "Num /", 0x6E: "Num ,",
    0xBB: "+", 0xBD: "−", 0xBC: ",", 0xBE: ".",
    0x20: "Space", 0x0D: "Enter", 0x09: "Tab", 0x08: "Backspace",
    0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓",
    0x21: "Page Up", 0x22: "Page Down", 0x24: "Home", 0x23: "End",
    0x2D: "Insert", 0x2E: "Delete", 0x13: "Pause",
}


def key_name(hotkey: Hotkey) -> str:
    """'Num +', 'Ctrl + G', 'F9' … for the settings panel and status line."""
    vk = hotkey.vk
    if vk in _NAMES:
        base = _NAMES[vk]
    elif 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        base = chr(vk)
    elif 0x60 <= vk <= 0x69:
        base = f"Num {vk - 0x60}"
    elif 0x70 <= vk <= 0x87:
        base = f"F{vk - 0x6F}"
    else:
        base = _system_key_name(vk) or f"Key {vk}"
    parts = [name for flag, name in ((MOD_CTRL, "Ctrl"), (MOD_SHIFT, "Shift"), (MOD_ALT, "Alt"))
             if hotkey.mods & flag]
    return " + ".join(parts + [base])


def _system_key_name(vk: int) -> str:
    """Windows' own name for a key this module doesn't name itself (Ä, ß …)."""
    if sys.platform != "win32":
        return ""
    try:
        user32 = ctypes.WinDLL("user32")
        scan = user32.MapVirtualKeyW(vk, 0)          # MAPVK_VK_TO_VSC
        buf = ctypes.create_unicode_buffer(64)
        if scan and user32.GetKeyNameTextW(scan << 16, buf, 64):
            name = buf.value
            # 'ä' -> 'Ä' like the A-Z keys; 'ß'.upper() is 'SS', so leave that
            return name.upper() if len(name) == 1 and len(name.upper()) == 1 else name
    except Exception:
        pass
    return ""


class KeyReader:
    """The keyboard as it is right now. `available` is False off Windows.

    `key_down(vk)` and `foreground_exe()` can be replaced (tests); by default
    they ask Windows."""

    def __init__(self, key_down: Optional[Callable[[int], bool]] = None,
                 foreground_exe: Optional[Callable[[], str]] = None):
        self.available = key_down is not None or sys.platform == "win32"
        self._key_down = key_down
        self._foreground_exe = foreground_exe
        self._fg_cache: tuple = (None, "")      # ((hwnd, pid), exe name)
        if key_down is None and sys.platform == "win32":
            self._setup_win32()

    # -- questions -------------------------------------------------------

    def is_held(self, hotkey: Hotkey) -> bool:
        """The key is down with exactly its modifiers: G alone doesn't fire
        for Ctrl + G, and Ctrl + G doesn't fire while Shift is down too."""
        if not self.available or not self._down(hotkey.vk):
            return False
        return all(bool(hotkey.mods & flag) == self._down(vk) for flag, vk in _MOD_KEYS)

    def vrchat_in_front(self) -> bool:
        return self.foreground_exe().lower() == VRCHAT_EXE

    def foreground_exe(self) -> str:
        """The exe name behind the foreground window ('' if unknown)."""
        if self._foreground_exe is not None:
            return self._foreground_exe()
        if not self.available:
            return ""
        try:
            return self._win32_foreground_exe()
        except Exception:
            return ""

    # -- Windows ---------------------------------------------------------

    def _down(self, vk: int) -> bool:
        if self._key_down is not None:
            return bool(self._key_down(vk))
        try:
            return bool(self._user32.GetAsyncKeyState(vk) & 0x8000)
        except Exception:
            return False

    def _setup_win32(self) -> None:
        from ctypes import wintypes as wt
        try:
            self._user32 = ctypes.WinDLL("user32")
            self._kernel32 = ctypes.WinDLL("kernel32")
        except Exception:
            self.available = False
            return
        u, k = self._user32, self._kernel32
        u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        u.GetAsyncKeyState.restype = ctypes.c_short
        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = wt.HWND
        u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        u.GetWindowThreadProcessId.restype = wt.DWORD
        k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        k.OpenProcess.restype = wt.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR,
                                                 ctypes.POINTER(wt.DWORD)]
        k.QueryFullProcessImageNameW.restype = wt.BOOL
        k.CloseHandle.argtypes = [wt.HANDLE]
        k.CloseHandle.restype = wt.BOOL

    def _win32_foreground_exe(self) -> str:
        from ctypes import wintypes as wt
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wt.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        key = (hwnd, pid.value)
        if self._fg_cache[0] == key:          # same window: no new process lookup
            return self._fg_cache[1]
        name = ""
        handle = self._kernel32.OpenProcess(0x1000, False, pid.value)   # QUERY_LIMITED_INFORMATION
        if handle:
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wt.DWORD(1024)
                if self._kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    name = os.path.basename(buf.value)
            finally:
                self._kernel32.CloseHandle(handle)
        self._fg_cache = (key, name)
        return name
