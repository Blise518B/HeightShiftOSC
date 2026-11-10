"""One HeightShift at a time (the VrcBeacon518 / VRCDollySync guard).

Two copies would both write the avatar's height: two preserve bursts after
every avatar change, two transitions fighting each other, and two writers of
one settings file. The guard is a loopback socket: whoever binds it owns the
config folder, and a later start hands over ("activate": the running window
comes to the front) and exits.

The port is derived from the config folder, so a test instance pointed at
another folder never blocks the real app.
"""
from __future__ import annotations

import hashlib
import logging
import socket
import threading
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

MAGIC = b"HEIGHTSHIFT/1"
_PORT_BASE, _PORT_SPAN = 43000, 4000


def port_for(data_dir) -> int:
    """A stable loopback port for this config folder."""
    key = str(Path(data_dir).resolve()).lower().encode("utf-8")
    digest = hashlib.sha256(key).digest()
    return _PORT_BASE + int.from_bytes(digest[:2], "big") % _PORT_SPAN


class Guard:
    """Holds the lock. `on_activate` fires (on the guard thread) when another
    start is attempted."""

    def __init__(self, sock: Optional[socket.socket]) -> None:
        self._sock = sock
        self.on_activate: Optional[Callable[[], None]] = None
        if sock is not None:
            threading.Thread(target=self._serve, name="instance-guard", daemon=True).start()

    def _serve(self) -> None:
        while True:
            sock = self._sock
            if sock is None:
                return
            try:
                conn, _ = sock.accept()
            except OSError:
                return  # socket closed on shutdown
            try:
                if conn.recv(64).startswith(MAGIC):
                    conn.sendall(MAGIC + b" ok")
                    callback = self.on_activate
                    if callback:
                        log.info("another start was attempted - activating")
                        callback()
            except OSError:
                pass
            finally:
                conn.close()

    def release(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _ping(port: int) -> bool:
    """True if the port is held by another instance of *this* app."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5) as conn:
            conn.sendall(MAGIC + b" activate")
            return conn.recv(64).startswith(MAGIC)
    except OSError:
        return False


def acquire(data_dir) -> Optional[Guard]:
    """Become the single instance, or None if one is already running."""
    port = port_for(data_dir)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))  # no SO_REUSEADDR: bind must fail if taken
        sock.listen(4)
        return Guard(sock)
    except OSError:
        sock.close()
    if _ping(port):
        return None  # an instance already owns this config folder
    log.warning("instance-guard port %d is busy but not ours; continuing without the guard", port)
    return Guard(None)
