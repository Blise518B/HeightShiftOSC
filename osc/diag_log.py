"""osc_diagnostics.log: a durable record of what the OSC connection did.

One line per event, appended across runs, next to the config file. Rotated
once it passes `max_bytes` (one `.1` backup is kept). Best effort: a log
that can't be written never reaches the OSC pipeline.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional


class DiagLog:
    def __init__(self, path: Optional[str], max_bytes: int = 1_000_000):
        self.path = path
        self.max_bytes = max_bytes
        self._lock = threading.Lock()

    def write(self, message: str) -> None:
        path = self.path
        if not path:
            return
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}\n"
        try:
            with self._lock:
                self._rotate_if_big(path)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
        except OSError:
            pass

    def _rotate_if_big(self, path: str) -> None:
        try:
            if os.path.getsize(path) <= self.max_bytes:
                return
            os.replace(path, path + ".1")
        except OSError:
            pass                      # missing (first write) or locked: keep appending
