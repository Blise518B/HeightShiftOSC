"""Tier 1 client of the 518 OSC Fallback Standard (OscRouter518/docs/STANDARD.md).

VRChat's mDNS listener dies after a few hours of gameplay; from then on it never
discovers a freshly started or re-advertised app, so the app receives nothing
until VRChat is restarted. OSC Router 518 starts with SteamVR, gets discovered
while VRChat is still healthy, and re-broadcasts VRChat's stream. This client
subscribes the app's existing OSC receive port there, so reception keeps working
whether or not VRChat can still see us directly. Duplicate delivery (native +
router) is harmless: avatar parameters are absolute values.

Stdlib only. A missing router is a silent no-op — this is the fallback, it must
never become a failure mode of its own.
"""
from __future__ import annotations

import socket
import struct
import threading
from typing import Callable, Optional

ROUTER = ("127.0.0.1", 51518)   # well-known constant from the standard
KEEPALIVE_S = 20.0              # spec: keep-alive every <= 30 s, TTL 90 s


def _pad(raw: bytes) -> bytes:
    raw += b"\x00"
    return raw + b"\x00" * (-len(raw) % 4)


def _control(address: str, port: int, name: str = "") -> bytes:
    """
    /router518/* control message: OSC address, the port, and optionally this program's
    name so the router's control panel can list who is connected by name rather than
    guessing from the port's owning process (from source we're all just "python").
    """
    if name:
        return (_pad(address.encode("ascii")) + _pad(b",is")
                + struct.pack(">i", port) + _pad(name.encode("ascii", "replace")))
    return _pad(address.encode("ascii")) + _pad(b",i") + struct.pack(">i", port)


class Router518KeepAlive:
    """Subscribes a receive port to the local router and keeps the lease alive.

    ``port_getter`` is called on every tick, so a listener whose bind failed
    (returns None) simply skips ticks until a real port exists, and a rebound
    server is picked up within one keep-alive interval.
    """

    def __init__(self, port_getter: Callable[[], Optional[int]],
                 name: str = "HeightShiftOSC") -> None:
        self._port_getter = port_getter
        self._name = name
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None
        self._last_port = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        self._thread = threading.Thread(
            target=self._run, name="Router518-KeepAlive", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                if self._last_port:
                    sock.sendto(_control("/router518/unsubscribe", self._last_port), ROUTER)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            sock = self._sock
            if sock is None:
                return
            try:
                # Drain /router518/ok acks; on Windows an ICMP port-unreachable
                # from a dead router also surfaces here as ConnectionResetError.
                try:
                    while True:
                        sock.recv(2048)
                except OSError:
                    pass
                port = self._port_getter() or 0
                if 0 < port <= 65535:
                    self._last_port = port
                    sock.sendto(_control("/router518/subscribe", port, self._name), ROUTER)
            except OSError:
                pass  # no router running: stay quiet and keep trying
            if self._stop.wait(KEEPALIVE_S):
                return
