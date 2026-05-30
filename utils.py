"""Small pure helpers shared across HeightShiftOSC. Kept dependency-free
so they're trivial to unit-test without Qt or the network."""

from __future__ import annotations

import ipaddress
import re

# A syntactically valid hostname: 1–253 chars total, dot-separated labels of
# 1–63 chars, each label alphanumeric with internal dashes (no leading or
# trailing dash). Doesn't resolve DNS — just rejects obvious garbage.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


def round_height_cm(value) -> int:
    """Round a height value to the nearest full centimeter."""
    return int(round(float(value)))


def is_valid_host(host: str) -> bool:
    """Return True if `host` is a usable OSC target — either a valid IP
    address (v4 or v6) or a syntactically valid hostname.

    Used to reject obviously-bad input in the IP field before it reaches the
    OSC client. Deliberately permissive — single-label names like
    ``"localhost"`` are accepted and we don't resolve DNS — but it rejects
    empty / whitespace input and strings with illegal characters
    (``"a b.c"``, ``"http://x"``, ``"1.2.3:9000"``) that the old
    ``"." in ip`` check let through.
    """
    if not isinstance(host, str):
        return False
    host = host.strip()
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    return bool(_HOSTNAME_RE.match(host))
