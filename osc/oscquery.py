"""OSCQuery for VRChat on this PC, both directions.

We SERVE two documents on a loopback HTTP server, so VRChat learns where to
send OSC (verified against vrc-oscquery-lib's OSCQueryHttpServer.cs; same
routing as OscGoesPurrr's vrchat_osc.py):

    ?HOST_INFO  -> host_info()  our name and OSC_IP / OSC_PORT (the UDP listener)
    /           -> tree()       the addresses we want to receive
    anything else -> 404

Answering ?HOST_INFO with the tree is the classic "connected but 0 packets"
bug: VRChat then never sends to us.

We READ VRChat's nodes (e.g. GET /avatar/eyeheight) with node_value().
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional

LOOPBACK = "127.0.0.1"

# What vrc-oscquery-lib publishes, so VRChat sees the shape it expects.
EXTENSIONS = {"ACCESS": True, "CLIPMODE": False, "RANGE": True, "TYPE": True, "VALUE": True}

ACCESS_READ_WRITE = 3


def host_info(name: str, osc_port: int) -> Dict[str, Any]:
    return {
        "NAME": name,
        "EXTENSIONS": dict(EXTENSIONS),
        "OSC_IP": LOOPBACK,
        "OSC_PORT": osc_port,
        "OSC_TRANSPORT": "UDP",
    }


def tree(name: str, osc_port: int, eyeheight_path: str, change_path: str) -> Dict[str, Any]:
    """The addresses we want. VRChat streams every avatar parameter to a
    client that lists any /avatar node; HeightShift only uses these two."""
    return {
        "NAME": name,
        "OSC_IP": LOOPBACK,
        "OSC_PORT": osc_port,
        "OSC_TRANSPORT": "UDP",
        "CONTENTS": {
            "avatar": {
                "FULL_PATH": "/avatar",
                "CONTENTS": {
                    "eyeheight": {"FULL_PATH": eyeheight_path, "TYPE": "f",
                                  "ACCESS": ACCESS_READ_WRITE},
                    "change": {"FULL_PATH": change_path, "TYPE": "s",
                               "ACCESS": ACCESS_READ_WRITE},
                },
            }
        },
    }


def node_value(node: Any) -> Any:
    """The VALUE of an OSCQuery node as VRChat sends it, e.g.
    {"FULL_PATH": "/avatar/eyeheight", "TYPE": "f", "VALUE": [1.29905224]}
    -> 1.29905224. None when the node carries no value."""
    if not isinstance(node, dict):
        return None
    value = node.get("VALUE")
    if isinstance(value, list):
        return value[0] if value else None
    return value


class _Handler(BaseHTTPRequestHandler):
    server: "_Server"

    def do_GET(self):  # noqa: N802
        raw = self.path or ""
        on_request = self.server.on_request
        if on_request is not None:
            try:
                on_request(raw, self.client_address[0] if self.client_address else "?")
            except Exception:
                pass
        # ?HOST_INFO as a query, or /HOST_INFO as a path: both appear in the wild.
        if "HOST_INFO" in raw.upper():
            self._send_json(self.server.host_info)
        elif raw.split("?", 1)[0] in ("/", ""):
            self._send_json(self.server.tree)
        else:
            self._send_json({"error": "not found"}, status=404)

    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Pragma", "no-cache")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 - BaseHTTPRequestHandler's name
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, host_info_doc, tree_doc, on_request):
        self.host_info = host_info_doc
        self.tree = tree_doc
        self.on_request = on_request
        super().__init__((LOOPBACK, 0), _Handler)


class PhonebookServer:
    """The HTTP server VRChat reads our two documents from.

    Loopback only, on a port the OS picks: Windows Defender Firewall silently
    blocks other processes (VRChat included) from reaching a socket bound to
    0.0.0.0 unless the exe was allowed, while 127.0.0.1 is never gated.
    OSCQuery between VRChat and an app on the same PC needs nothing more."""

    def __init__(self, host_info_doc: Dict[str, Any], tree_doc: Dict[str, Any],
                 on_request: Optional[Callable[[str, str], None]] = None):
        self._server = _Server(host_info_doc, tree_doc, on_request)
        self.port: int = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True, name="OSC-Phonebook")
        self._thread.start()

    def stop(self) -> None:
        try:
            self._server.shutdown()
        finally:
            self._server.server_close()
