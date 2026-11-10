"""The console window run.bat opens (Windows only)."""

from __future__ import annotations

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

SW_HIDE, SW_SHOW = 0, 5


class ConsoleWindow:
    """Hides the console on request, and ALWAYS shows it again when the app
    exits (main() registers restore() with atexit). Before, a hidden console
    stayed hidden after exit, so run.bat's closing `pause` sat in an invisible
    window forever (one stray cmd.exe per launch) and a crash's traceback was
    never visible."""

    def __init__(self) -> None:
        self.hwnd = 0
        self.hidden = False
        if sys.platform == "win32":
            try:
                self._user32 = ctypes.WinDLL("user32")
                self.hwnd = ctypes.WinDLL("kernel32").GetConsoleWindow()
            except Exception:
                self.hwnd = 0

    @property
    def available(self) -> bool:
        return bool(self.hwnd)

    def set_hidden(self, hide: bool) -> None:
        if not self.hwnd:
            return
        try:
            self._user32.ShowWindow(self.hwnd, SW_HIDE if hide else SW_SHOW)
            self.hidden = hide
        except Exception as e:
            logger.error(f"Could not toggle console visibility: {e}")

    def restore(self) -> None:
        if self.hidden:
            self.set_hidden(False)
