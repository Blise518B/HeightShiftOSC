"""
osc_manager.py — VRChat OSC + OSCQuery for HeightShiftOSC.

Single class that owns the entire OSC pipeline:

  * mDNS discovery of VRChat's OSCQuery server
  * VRCFT-style deferred bind (no UDP / HTTP sockets until VRChat appears)
  * Per-launch unique mDNS service name so VRChat can't cache stale ports
  * Proper `?HOST_INFO` endpoint distinct from the root OSCQuery tree
  * Loopback-only HTTP phonebook (avoids Windows Defender Firewall pitfalls)
  * Health-check thread that flips us to disconnected on OSCQuery silence
  * Silent-connection watchdog with progressive self-heal:
      log → re-poll → re-register mDNS under a fresh name
  * Persistent diagnostics log at %APPDATA%/HeightShiftOSC/osc_diagnostics.log

The architecture mirrors OscGoesPurrr's `vrchat_osc.py` — the same lessons
apply (we hit the exact "connected but 0 packets" failure mode before
that code existed). HeightShiftOSC is much smaller so this is a trimmed
port: no parameter store, no rate limiting, no bundle sending — just
`/avatar/eyeheight` and `/avatar/change`.
"""

from __future__ import annotations

import json
import logging
import random
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient
from zeroconf import ServiceBrowser, ServiceInfo, ServiceStateChange, Zeroconf

from constants import (
    APP_NAME,
    BROWSER_REFRESH_S,
    DIAG_LOG_INTERVAL_S,
    HEALTH_CHECK_INTERVAL_S,
    LOG_FILE_MAX_BYTES,
    LOG_FILE_NAME,
    SILENT_REPROBE_S,
    SILENT_REREGISTER_S,
    SILENT_THRESHOLD_S,
    VRC_DEFAULT_PORT,
    VRCHAT_AVATAR_CHANGE_PATH,
    VRCHAT_HTTP_TIMEOUT,
    VRCHAT_OSC_PATH,
)

logger = logging.getLogger(__name__)


class OSCQueryHandler(BaseHTTPRequestHandler):
    """HTTP handler implementing the OSCQuery phonebook protocol.

    Three distinct paths matter for VRChat's client (verified by reading
    vrc-oscquery-lib's `OSCQueryHttpServer.cs`):

      * `?HOST_INFO`  → `HostInfo` JSON (NAME/EXTENSIONS/OSC_IP/OSC_PORT/
                        OSC_TRANSPORT). This is THE document VRChat uses
                        to learn where to send our OSC UDP packets.
      * `/`           → the OSCQuery tree (NAME + CONTENTS describing the
                        parameters we want to receive).
      * other         → 404.

    Returning the tree for `?HOST_INFO` is the canonical "connected but
    0 packets" bug. Don't.
    """

    def __init__(self, *args, host_info=None, osc_tree=None,
                 on_request=None, on_raw_connection=None, **kwargs):
        self.host_info = host_info
        self.osc_tree = osc_tree
        self._on_request = on_request
        self._on_raw_connection = on_raw_connection
        super().__init__(*args, **kwargs)

    def setup(self):
        cb = self._on_raw_connection
        if cb is not None:
            try:
                cb()
            except Exception:
                pass
        super().setup()

    def do_GET(self):
        client = self.client_address[0] if self.client_address else "?"
        try:
            if self._on_request is not None:
                self._on_request(self.path, client)
        except Exception:
            pass

        raw = self.path or ""
        if "HOST_INFO" in raw.upper():
            self._send_json(self.host_info or {})
            return
        path_only = raw.split("?", 1)[0]
        if path_only in ("/", "", "/index"):
            self._send_json(self.osc_tree or {})
            return
        self.send_response(404)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"not found"}')

    def _send_json(self, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Pragma", "no-cache")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class VRChatOSCManager:
    """Owns mDNS discovery, the OSCQuery HTTP phonebook, UDP send/receive,
    and the diagnostics / watchdog threads.

    Public surface:
      * start() / stop()
      * send_height(cm)
      * query_height_via_http() — one-shot, returns cm or None
      * properties: is_connected, vrc_ip, vrc_osc_port, local_listen_port
      * callbacks: on_connected, on_disconnected, on_height_received,
                   on_avatar_change, on_log
    """

    _SUFFIX_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    _SUFFIX_LEN = 6

    @classmethod
    def _make_service_suffix(cls) -> str:
        return "".join(random.choice(cls._SUFFIX_CHARS) for _ in range(cls._SUFFIX_LEN))

    def __init__(self, local_listen_port: int = 0):
        self.zeroconf: Optional[Zeroconf] = None
        self.osc_client: Optional[SimpleUDPClient] = None
        self.osc_server: Optional[ThreadingOSCUDPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.dispatcher = Dispatcher()
        self.dispatcher.set_default_handler(self._handle_incoming_osc)

        # Per-launch unique mDNS service name. Without the suffix, VRChat
        # caches `HeightShiftOSC._oscjson._tcp.local.` across our restarts
        # and keeps sending UDP to a port we no longer own — exact match
        # for the "connected but 0 packets" failure mode.
        self._service_base = APP_NAME
        self._service_suffix = self._make_service_suffix()
        self.service_short_name = f"{self._service_base}-{self._service_suffix}"
        self.service_host_name = f"{self.service_short_name}.local."

        # File log path is resolved lazily; never let logging take down OSC.
        self._log_file_path: Optional[Path] = self._compute_log_path()
        self._log_file_lock = threading.Lock()

        # Connection state
        self.vrc_ip = "127.0.0.1"
        self.vrc_osc_port = VRC_DEFAULT_PORT
        self.http_port: Optional[int] = None
        self.local_listen_port = local_listen_port
        self.http_listen_port: Optional[int] = None
        self.is_connected = False
        # Serialises connected/disconnected transitions so the health-check
        # thread and the mDNS-removed handler can't both flip the flag and
        # double-fire the disconnect callback.
        self._state_lock = threading.Lock()

        # mDNS service info (populated after first VRChat discovery)
        self.service_info: Optional[ServiceInfo] = None
        self.service_info_json: Optional[ServiceInfo] = None
        self.host_info: Dict[str, Any] = {}
        self.osc_tree: Dict[str, Any] = {}

        # Cache of every avatar-tree parameter VRChat has filled in. Keys
        # are full OSC paths (e.g. "/avatar/eyeheight"); values are the
        # latest VALUE seen via a fetch or an incoming OSC packet. Created
        # eagerly here (not lazily) so the several threads that touch it —
        # the OSC handler, the resolver, the prefetch, and HTTP queries —
        # can never race on first-init.
        self._param_cache: Dict[str, Any] = {}

        # User-facing callbacks
        self.on_connected: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_disconnected: Optional[Callable[[], None]] = None
        self.on_height_received: Optional[Callable[[float], None]] = None
        self.on_avatar_change: Optional[Callable[[str], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None

        # Diagnostics counters (monotonic int writes, no lock needed)
        self._last_packet_time: Optional[float] = None
        self._packets_handled = 0
        self._packets_handled_at_last_log = 0
        self._handler_exceptions = 0
        self._last_handler_error = ""
        self._connected_since: Optional[float] = None
        self._silent_warning_logged = False
        self._silent_reprobe_attempted = False
        self._silent_rereg_attempted = False
        self._mdns_rereg_count = 0
        self._first_packet_logged = False
        self._phonebook_requests = 0
        self._raw_http_connections = 0

        # VRCFT-style "first VRChat discovery" latch.
        self._vrchat_first_discovered_done = False
        self._discovery_lock = threading.Lock()

        self._shutdown = threading.Event()
        self._health_thread: Optional[threading.Thread] = None
        self._diag_thread: Optional[threading.Thread] = None
        self._mdns_refresh_thread: Optional[threading.Thread] = None
        self.browser: Optional[ServiceBrowser] = None
        self.http_server: Optional[ThreadingHTTPServer] = None

    # ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        """Emit a `[OSC]` diagnostic line. Routes through the on_log
        callback (typically the UI log), the Python logger, and the
        persistent log file."""
        ts = time.strftime("%H:%M:%S")
        line = f"[OSC] {message}"
        logger.info(message)
        self._write_log_file(ts, message)
        cb = self.on_log
        if cb is not None:
            try:
                cb(line)
            except Exception:
                pass

    def _compute_log_path(self) -> Optional[Path]:
        try:
            appdata = Path.home() / "AppData" / "Roaming" / APP_NAME
            appdata.mkdir(parents=True, exist_ok=True)
            return appdata / LOG_FILE_NAME
        except Exception:
            return None

    def _write_log_file(self, timestamp: str, message: str) -> None:
        path = self._log_file_path
        if path is None:
            return
        try:
            with self._log_file_lock:
                try:
                    if path.exists() and path.stat().st_size > LOG_FILE_MAX_BYTES:
                        backup = path.with_suffix(path.suffix + ".1")
                        if backup.exists():
                            backup.unlink()
                        path.rename(backup)
                except Exception:
                    pass
                with open(path, "a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%Y-%m-%d')} {timestamp}  {message}\n")
        except Exception:
            pass

    def get_log_file_path(self) -> Optional[str]:
        return str(self._log_file_path) if self._log_file_path else None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start mDNS discovery and the diagnostic threads. UDP / HTTP
        sockets are NOT opened until VRChat appears on the bus."""
        self._shutdown.clear()
        self._vrchat_first_discovered_done = False
        self.zeroconf = Zeroconf()
        self._log(
            "start(): VRCFT-style deferred bind. Waiting for VRChat to appear "
            f"on _oscjson._tcp.local. (requested local port={self.local_listen_port})"
        )
        self._start_discovery()
        self._start_health_check()
        self._start_diagnostics()

    def stop(self) -> None:
        self._shutdown.set()
        # Stop the eyeheight resolver loop if it's still grinding.
        resolver_stop = getattr(self, "_eh_resolver_stop", None)
        if resolver_stop is not None:
            resolver_stop.set()
        # Unregister mDNS services so VRChat sees us go cleanly.
        if self.zeroconf:
            try:
                self.zeroconf.unregister_all_services()
            except Exception:
                pass
            try:
                self.zeroconf.close()
            except Exception:
                pass
            self.zeroconf = None
        if self.osc_server:
            try:
                self.osc_server.shutdown()
            except Exception:
                pass
            try:
                self.osc_server.server_close()
            except Exception:
                pass
            self.osc_server = None
        if self.http_server:
            try:
                self.http_server.shutdown()
            except Exception:
                pass
            try:
                self.http_server.server_close()
            except Exception:
                pass
            self.http_server = None

    # ------------------------------------------------------------------
    # mDNS discovery
    # ------------------------------------------------------------------

    def _start_discovery(self) -> None:
        self.browser = ServiceBrowser(
            self.zeroconf, "_oscjson._tcp.local.",
            handlers=[self._on_service_state_change],
        )
        self._mdns_refresh_thread = threading.Thread(
            target=self._mdns_refresh_loop, daemon=True, name="OSC-mDNSRefresh"
        )
        self._mdns_refresh_thread.start()

    def _mdns_refresh_loop(self) -> None:
        """Rebuild the ServiceBrowser periodically while disconnected so
        python-zeroconf re-queries the bus. Mirrors VRCOSC's refreshServices
        repeater — recovers from the case where VRChat's announcement was
        missed during our startup."""
        cycles_silent = 0
        while not self._shutdown.is_set():
            if self._shutdown.wait(BROWSER_REFRESH_S):
                return
            if self.is_connected:
                cycles_silent = 0
                continue
            cycles_silent += 1
            try:
                old = self.browser
                if old is not None:
                    try:
                        old.cancel()
                    except Exception:
                        pass
                if self.zeroconf is None:
                    return
                self.browser = ServiceBrowser(
                    self.zeroconf, "_oscjson._tcp.local.",
                    handlers=[self._on_service_state_change],
                )
                if cycles_silent == 1 or cycles_silent % 6 == 0:
                    self._log(
                        f"mDNS browser refreshed (cycle #{cycles_silent}) — "
                        "still waiting for VRChat"
                    )
            except Exception as e:
                if cycles_silent <= 3:
                    self._log(f"mDNS refresh failed: {type(e).__name__}: {e}")

    def _on_service_state_change(self, zeroconf: Zeroconf, service_type: str,
                                 name: str, state_change: ServiceStateChange):
        try:
            self._log(f"mDNS {state_change.name}: {name}")
        except Exception:
            pass
        if state_change == ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info and "VRChat" in name:
                self._log(
                    f"VRChat OSCQuery discovered: name={name} port={info.port} "
                    f"addresses={[socket.inet_ntoa(a) for a in (info.addresses or []) if len(a) == 4]}"
                )
                self.http_port = info.port
                self.vrc_ip = "127.0.0.1"

                # Fire the eyeheight query IMMEDIATELY — same behaviour as the
                # original HeightShiftOSC, which queried the moment it had
                # VRChat's HTTP port via mDNS, without waiting for any
                # handshake. This call goes to VRChat's HTTP server and is
                # independent of whether VRChat has discovered us yet.
                threading.Thread(
                    target=self._fetch_eyeheight_direct,
                    kwargs={"attempt": 0},  # attempt 0 = "pre-handshake snapshot"
                    daemon=True, name="OSC-EarlyEyeheight",
                ).start()

                with self._discovery_lock:
                    needs_first_setup = not self._vrchat_first_discovered_done
                    if needs_first_setup:
                        self._vrchat_first_discovered_done = True
                if needs_first_setup:
                    try:
                        self._on_vrchat_first_discovered()
                    except Exception as e:
                        self._log(f"VRCFT-style setup failed: {type(e).__name__}: {e}")
                        with self._discovery_lock:
                            self._vrchat_first_discovered_done = False
                        return
                self._fetch_osc_ports()
        elif state_change == ServiceStateChange.Removed:
            if "VRChat" in name:
                self._log(f"VRChat mDNS Removed: {name}")
                self._handle_disconnect("VRChat mDNS service removed")

    def _on_vrchat_first_discovered(self) -> None:
        """VRCFT's FirstClientDiscovered, ported. Runs once per `start()`
        cycle the first time VRChat appears on mDNS."""
        # Refresh the suffix on every first-discovery so a quick
        # disconnect → connect cycle still presents a fresh name.
        self._service_suffix = self._make_service_suffix()
        self.service_short_name = f"{self._service_base}-{self._service_suffix}"
        self.service_host_name = f"{self.service_short_name}.local."

        self._log(
            "VRChat observed on bus — running VRCFT-style FirstClientDiscovered: "
            f"binding sockets and advertising as {self.service_short_name}"
        )
        self._setup_osc()

    # ------------------------------------------------------------------
    # UDP server + HTTP phonebook + mDNS advertisement
    # ------------------------------------------------------------------

    def _setup_osc(self) -> None:
        if self.osc_server:
            self._log("tearing down previous OSC server before rebind")
            try:
                self.osc_server.shutdown()
            except Exception:
                pass

        self.dispatcher.set_default_handler(self._handle_incoming_osc)

        # Bind to 127.0.0.1 explicitly — see the comment in OscGoesPurrr's
        # vrchat_osc.py. Windows Defender silently drops inbound UDP to
        # 0.0.0.0-bound sockets unless the user has approved a firewall
        # rule for our exe. VRChat and the OSCQuery handshake are
        # localhost-only protocols, so loopback is correct.
        udp_bind_ip = "127.0.0.1"
        try:
            self.osc_server = ThreadingOSCUDPServer(
                (udp_bind_ip, self.local_listen_port), self.dispatcher
            )
        except OSError as e:
            self._log(
                f"OSC UDP bind FAILED on {udp_bind_ip}:{self.local_listen_port} — "
                f"{type(e).__name__}: {e}. Another OSC app likely owns this port."
            )
            raise

        if self.local_listen_port == 0:
            self.local_listen_port = self.osc_server.server_address[1]

        actual = self.osc_server.socket.getsockname()
        self._log(f"OSC UDP listener bound to {actual[0]}:{actual[1]}")

        self.server_thread = threading.Thread(
            target=self.osc_server.serve_forever, daemon=True, name="OSC-UDPServer"
        )
        self.server_thread.start()

        self.osc_client = SimpleUDPClient(self.vrc_ip, self.vrc_osc_port)

        self._start_phonebook_server()
        self._advertise_service()

    def _start_phonebook_server(self) -> None:
        """HTTP phonebook is loopback-only by design — see vrchat_osc.py
        for the Windows Firewall rationale."""
        http_bind_ip = "127.0.0.1"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((http_bind_ip, 0))
            self.http_listen_port = s.getsockname()[1]

        self.host_info = {
            "NAME": APP_NAME,
            "EXTENSIONS": {
                "ACCESS": True,
                "CLIPMODE": False,
                "RANGE": True,
                "TYPE": True,
                "VALUE": True,
            },
            "OSC_IP": "127.0.0.1",
            "OSC_PORT": self.local_listen_port,
            "OSC_TRANSPORT": "UDP",
        }

        self.osc_tree = {
            "NAME": APP_NAME,
            "OSC_IP": "127.0.0.1",
            "OSC_PORT": self.local_listen_port,
            "OSC_TRANSPORT": "UDP",
            "CONTENTS": {
                "avatar": {
                    "FULL_PATH": "/avatar",
                    "CONTENTS": {
                        "eyeheight": {
                            "FULL_PATH": VRCHAT_OSC_PATH,
                            "TYPE": "f",
                            "ACCESS": 3,
                        },
                        "change": {
                            "FULL_PATH": VRCHAT_AVATAR_CHANGE_PATH,
                            "TYPE": "s",
                            "ACCESS": 3,
                        },
                    },
                }
            },
        }

        self.http_server = ThreadingHTTPServer(
            (http_bind_ip, self.http_listen_port),
            lambda *args, **kwargs: OSCQueryHandler(
                *args,
                host_info=self.host_info,
                osc_tree=self.osc_tree,
                on_request=self._on_phonebook_request,
                on_raw_connection=self._on_raw_http_connection,
                **kwargs,
            ),
        )
        threading.Thread(
            target=self.http_server.serve_forever, daemon=True, name="OSC-Phonebook"
        ).start()
        self._log(
            f"phonebook HTTP server started on {http_bind_ip}:{self.http_listen_port} "
            "(loopback-only)"
        )

    def _on_phonebook_request(self, path: str, client: str) -> None:
        self._phonebook_requests += 1
        if self._phonebook_requests <= 3:
            self._log(f"phonebook GET #{self._phonebook_requests} path={path} from={client}")

    def _on_raw_http_connection(self) -> None:
        self._raw_http_connections += 1

    def _advertise_service(self) -> None:
        if self.zeroconf is None or self.http_listen_port is None:
            return
        short = self.service_short_name
        host = self.service_host_name

        osc_service_name = f"{short}._osc._udp.local."
        self.service_info = ServiceInfo(
            "_osc._udp.local.",
            osc_service_name,
            addresses=[socket.inet_aton("127.0.0.1")],
            port=self.local_listen_port,
            properties={"version": "1.0".encode("utf-8")},
            server=host,
        )
        try:
            self.zeroconf.register_service(self.service_info)
            self._log(
                f"mDNS register OK: {osc_service_name} → 127.0.0.1:{self.local_listen_port}"
            )
        except Exception as e:
            self._log(f"mDNS register FAILED for {osc_service_name}: {type(e).__name__}: {e}")

        json_service_name = f"{short}._oscjson._tcp.local."
        self.service_info_json = ServiceInfo(
            "_oscjson._tcp.local.",
            json_service_name,
            addresses=[socket.inet_aton("127.0.0.1")],
            port=self.http_listen_port,
            properties={"version": "1.0".encode("utf-8")},
            server=host,
        )
        try:
            self.zeroconf.register_service(self.service_info_json)
            self._log(
                f"mDNS register OK: {json_service_name} → 127.0.0.1:{self.http_listen_port}"
            )
        except Exception as e:
            self._log(f"mDNS register FAILED for {json_service_name}: {type(e).__name__}: {e}")

    def reregister_mdns(self) -> bool:
        """Rip our mDNS advertisement off the network and re-publish under
        a fresh unique name. Forces VRChat to treat us as a brand-new OSC
        client and re-query our phonebook."""
        if self.zeroconf is None or self.http_listen_port is None:
            self._log("re-publish mDNS skipped: not yet advertising")
            return False
        self._mdns_rereg_count += 1
        old_short = self.service_short_name
        self._log(
            f"re-registering mDNS service (cycle #{self._mdns_rereg_count}) — "
            "fresh unique name to bust VRChat's cache"
        )
        try:
            if self.service_info is not None:
                try:
                    self.zeroconf.unregister_service(self.service_info)
                except Exception as e:
                    self._log(f"unregister(_osc._udp) warning: {type(e).__name__}: {e}")
            if self.service_info_json is not None:
                try:
                    self.zeroconf.unregister_service(self.service_info_json)
                except Exception as e:
                    self._log(f"unregister(_oscjson._tcp) warning: {type(e).__name__}: {e}")

            self._service_suffix = self._make_service_suffix()
            self.service_short_name = f"{self._service_base}-{self._service_suffix}"
            self.service_host_name = f"{self.service_short_name}.local."
            self._log(f"new mDNS name: {self.service_short_name} (was {old_short})")
            time.sleep(0.5)
            self._advertise_service()
            return True
        except Exception as e:
            self._log(f"reregister_mdns FAILED: {type(e).__name__}: {e}")
            return False

    # ------------------------------------------------------------------
    # OSCQuery HTTP queries (against VRChat)
    # ------------------------------------------------------------------

    def _fetch_osc_ports(self) -> None:
        """Resolve VRChat's UDP OSC port via `?HOST_INFO`, send the
        handshake ping, mark us connected, and pre-load every avatar
        parameter VRChat has already filled in via the OSCQuery tree.

        Mirrors OscGoesPurrr's flow: HOST_INFO for the port + handshake
        ping + immediate `/avatar` walk so `/avatar/eyeheight` is in our
        cache by the time the UI asks for it — even when VRChat hasn't
        yet broadcast it as an OSC packet."""
        try:
            self.vrc_osc_port = self._resolve_vrc_osc_port() or VRC_DEFAULT_PORT
            self._log(
                f"VRChat OSC port resolved: {self.vrc_osc_port} "
                f"(our listen port: {self.local_listen_port})"
            )

            self.osc_client = SimpleUDPClient(self.vrc_ip, self.vrc_osc_port)
            with self._state_lock:
                self.is_connected = True
            self._connected_since = time.time()
            self._silent_warning_logged = False
            self._silent_reprobe_attempted = False
            self._silent_rereg_attempted = False
            self._first_packet_logged = False

            # Handshake ping from the SERVER socket so VRChat learns the
            # exact port we listen on (not an ephemeral sendto port).
            # This is what flips VRChat into "broadcast all avatar params
            # to this client" mode.
            if self.osc_server and self.osc_server.socket:
                ping = OscMessageBuilder(address=f"/{APP_NAME}/ping")
                ping.add_arg(True)
                self.osc_server.socket.sendto(
                    ping.build().dgram, (self.vrc_ip, self.vrc_osc_port)
                )
                self._log(
                    f"sent handshake ping to {self.vrc_ip}:{self.vrc_osc_port} "
                    f"from local socket {self.osc_server.socket.getsockname()}"
                )

            if self.on_connected:
                try:
                    self.on_connected(self.ports)
                except Exception as e:
                    self._log(f"on_connected callback error: {type(e).__name__}: {e}")

            # OGP-style: immediately walk VRChat's `/avatar` subtree so we
            # pick up every parameter VRChat has filled in (including
            # `/avatar/eyeheight`). 1.5s pre-delay so VRChat has time to
            # finish building the tree.
            threading.Thread(
                target=self._prefetch_avatar_tree,
                daemon=True, name="OSC-AvatarPrefetch",
            ).start()
        except Exception as e:
            self._log(f"failed to fetch OSCQuery data: {type(e).__name__}: {e}")

    def _resolve_vrc_osc_port(self) -> Optional[int]:
        """Ask VRChat for its UDP OSC port. Tries `?HOST_INFO` first (the
        canonical OSCQuery endpoint for this), then the root tree (where
        some older builds put it), and finally returns None to let the
        caller fall back to the well-known default (9000)."""
        if not self.http_port:
            return None
        # 1. ?HOST_INFO — the OSCQuery-compliant location.
        try:
            r = requests.get(
                f"http://{self.vrc_ip}:{self.http_port}/?HOST_INFO",
                timeout=VRCHAT_HTTP_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                port = data.get("OSC_PORT") or data.get("OSC Port")
                if port:
                    self._log(f"resolved VRChat OSC port via HOST_INFO: {port}")
                    return int(port)
        except Exception as e:
            self._log(f"HOST_INFO query failed: {type(e).__name__}: {e}")
        # 2. Root tree — some VRChat builds put OSC_PORT here too.
        try:
            r = requests.get(
                f"http://{self.vrc_ip}:{self.http_port}/",
                timeout=VRCHAT_HTTP_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                port = data.get("OSC_PORT") or data.get("OSC Port")
                if port:
                    self._log(f"resolved VRChat OSC port via root tree: {port}")
                    return int(port)
        except Exception as e:
            self._log(f"root tree port query failed: {type(e).__name__}: {e}")
        return None

    # ------------------------------------------------------------------
    # Avatar parameter cache (OGP-style)
    # ------------------------------------------------------------------
    #
    # `self._param_cache` (created in __init__) maps full OSC paths to the
    # latest VALUE seen — fed by `_prefetch_avatar_tree`,
    # `fetch_avatar_parameters`, and every incoming OSC packet; consumed by
    # `query_height_via_http` and the eyeheight resolver.

    def _prefetch_avatar_tree(self) -> None:
        """Background pre-fetch fired right after a successful handshake.
        Sleeps briefly so VRChat finishes building its OSCQuery tree, then
        kicks off the eyeheight resolver loop that keeps trying until
        VRChat coughs up a value (or we hit the attempt cap)."""
        time.sleep(1.5)
        try:
            count = self.fetch_avatar_parameters()
            eye_keys = [k for k in self._param_cache.keys() if "eye" in k.lower()]
            self._log(
                f"avatar tree prefetched: {count} parameter(s) cached. "
                f"Keys containing 'eye': {eye_keys or '<none>'}"
            )
        except Exception as e:
            self._log(f"avatar tree prefetch failed: {type(e).__name__}: {e}")

        # Start the resolver loop — keeps trying every few seconds until
        # we get a value. Survives the "VRChat hadn't built the
        # /avatar/eyeheight node yet" case.
        self._start_eyeheight_resolver()

    def _refetch_after_avatar_change(self) -> None:
        """Re-walk the avatar tree after a swap so the cache reflects the
        new avatar. Brief sleep mirrors OGP's debounce — VRChat needs a
        moment to finish loading the new avatar's parameter set."""
        time.sleep(1.5)
        try:
            count = self.fetch_avatar_parameters()
            eye_keys = [k for k in self._param_cache.keys() if "eye" in k.lower()]
            self._log(
                f"avatar tree refetched after change: {count} parameter(s) cached. "
                f"Keys containing 'eye': {eye_keys or '<none>'}"
            )
        except Exception as e:
            self._log(f"avatar refetch failed: {type(e).__name__}: {e}")

        # Always re-arm the resolver after an avatar change — eyeheight
        # may differ on the new avatar and we want it picked up promptly.
        self._start_eyeheight_resolver()

    # Resolver settings — how aggressive to be when polling for eyeheight.
    _EH_RESOLVER_MAX_ATTEMPTS = 12
    _EH_RESOLVER_INTERVAL_S = 3.0

    def _start_eyeheight_resolver(self) -> None:
        """Spawn (or restart) the background loop that keeps trying to
        resolve eyeheight from VRChat. Stops as soon as a value is in
        the cache or after `_EH_RESOLVER_MAX_ATTEMPTS` tries (~36 s by
        default — long enough to outlast a slow avatar load)."""
        # If an earlier resolver is still running, signal it to stop.
        prev = getattr(self, "_eh_resolver_stop", None)
        if prev is not None:
            prev.set()

        stop = threading.Event()
        self._eh_resolver_stop = stop

        def loop() -> None:
            for attempt in range(1, self._EH_RESOLVER_MAX_ATTEMPTS + 1):
                if stop.is_set() or self._shutdown.is_set():
                    return
                # Cache hit? Done.
                cached = self._param_cache.get(VRCHAT_OSC_PATH)
                if cached is not None:
                    self._log(
                        f"eyeheight resolver: value already in cache ({cached!r}), "
                        f"stopping after attempt {attempt}"
                    )
                    return
                # Try the direct HTTP endpoint.
                result = self._fetch_eyeheight_direct(attempt=attempt)
                if result is not None:
                    self._log(f"eyeheight resolver: succeeded on attempt {attempt}")
                    return
                # Wait before retry (use stop event so we exit promptly
                # on shutdown).
                if stop.wait(self._EH_RESOLVER_INTERVAL_S):
                    return
            self._log(
                f"eyeheight resolver: gave up after {self._EH_RESOLVER_MAX_ATTEMPTS} "
                "attempts. VRChat may not be exposing /avatar/eyeheight via "
                "OSCQuery for this avatar — try changing height once in-game "
                "to force a push."
            )

        threading.Thread(target=loop, daemon=True, name="OSC-EyeheightResolver").start()

    def _fetch_eyeheight_direct(self, attempt: int = 1) -> Optional[float]:
        """Hit `/avatar/eyeheight` as its own URL and stuff the result
        into the cache. Returns the metres value, or None on miss.

        Logs verbosely on every call so when this still fails we can see
        exactly what VRChat said. `attempt` is purely for the log."""
        if not self.http_port:
            self._log(f"eyeheight direct GET skipped (attempt {attempt}): no http_port yet")
            return None
        url = f"http://{self.vrc_ip}:{self.http_port}{VRCHAT_OSC_PATH}"
        self._log(f"eyeheight direct GET (attempt {attempt}): {url}")
        try:
            r = requests.get(url, timeout=VRCHAT_HTTP_TIMEOUT)
        except Exception as e:
            self._log(
                f"eyeheight direct GET (attempt {attempt}) FAILED: "
                f"{type(e).__name__}: {e}"
            )
            return None
        if r.status_code != 200:
            body_preview = (r.text or "")[:300]
            self._log(
                f"eyeheight direct GET (attempt {attempt}) HTTP {r.status_code}; "
                f"body: {body_preview!r}"
            )
            return None
        body_preview = (r.text or "")[:300]
        try:
            data = r.json()
        except Exception as e:
            self._log(
                f"eyeheight direct GET (attempt {attempt}) JSON parse failed: "
                f"{type(e).__name__}: {e}; body: {body_preview!r}"
            )
            return None
        self._log(
            f"eyeheight direct GET (attempt {attempt}) response keys={list(data.keys())} "
            f"body[:300]={body_preview!r}"
        )
        val = data.get("VALUE")
        if isinstance(val, list) and val:
            val = val[0]
        if val is None:
            self._log(
                f"eyeheight direct GET (attempt {attempt}): no VALUE field. "
                f"Full data: {data!r}"
            )
            return None
        try:
            meters = float(val)
        except (TypeError, ValueError):
            self._log(
                f"eyeheight direct GET (attempt {attempt}): VALUE not numeric "
                f"({val!r})"
            )
            return None
        self._param_cache[VRCHAT_OSC_PATH] = meters
        self._log(f"eyeheight resolved via direct GET: {meters}m")
        # Fire the height callback so the UI updates as soon as we
        # resolve, not on the next controller poll.
        cb = self.on_height_received
        if cb is not None:
            try:
                cb(meters)
            except Exception as e:
                self._log(f"on_height_received error from resolver: {type(e).__name__}: {e}")
        return meters

    def fetch_avatar_parameters(self) -> int:
        """Walk VRChat's `/avatar` subtree and populate the parameter
        cache with every node that carries a VALUE. Returns how many
        parameters were cached this pass."""
        if not self.http_port:
            return 0
        # `/avatar` is the parent of eyeheight, change, AND the
        # avatar-specific parameter subtree. Walking it once gets us
        # everything VRChat is currently exposing.
        url = f"http://{self.vrc_ip}:{self.http_port}/avatar"
        try:
            r = requests.get(url, timeout=VRCHAT_HTTP_TIMEOUT)
        except Exception as e:
            self._log(f"GET /avatar failed: {type(e).__name__}: {e}")
            return 0
        if r.status_code != 200:
            self._log(f"GET /avatar returned HTTP {r.status_code}")
            return 0
        try:
            data = r.json()
        except Exception as e:
            self._log(f"GET /avatar JSON parse failed: {type(e).__name__}: {e}")
            return 0

        flat = self._flatten_oscquery_node(data)
        cached = 0
        for path, value in flat.items():
            # OSCQuery wraps single values in a one-element list; unwrap.
            if isinstance(value, list) and len(value) == 1:
                value = value[0]
            self._param_cache[path] = value
            cached += 1
        return cached

    @classmethod
    def _flatten_oscquery_node(cls, node: dict) -> Dict[str, Any]:
        """Walk an OSCQuery JSON tree, returning {FULL_PATH: VALUE} for
        every node that carries a VALUE field. Mirrors OGP's helper."""
        results: Dict[str, Any] = {}
        if not isinstance(node, dict):
            return results
        if "FULL_PATH" in node and "VALUE" in node:
            results[node["FULL_PATH"]] = node["VALUE"]
        contents = node.get("CONTENTS")
        if isinstance(contents, dict):
            for child in contents.values():
                results.update(cls._flatten_oscquery_node(child))
        return results

    def get_cached_parameter(self, path: str) -> Any:
        """Return the cached VALUE for an OSC path, or None if we haven't
        seen one yet. Cache is fed by `fetch_avatar_parameters` and by
        every incoming OSC packet."""
        return self._param_cache.get(path)

    def query_height_via_http(self) -> Optional[float]:
        """Return VRChat's current `/avatar/eyeheight` in metres, or None
        if VRChat hasn't filled it in.

        Lookup order:
          1. Cache (fed by the prefetch + every incoming OSC packet).
          2. Walk `/avatar` and re-check the cache.
          3. Direct GET on `/avatar/eyeheight` — works even when VRChat
             doesn't list eyeheight under `/avatar` in its tree."""
        cached = self._param_cache.get(VRCHAT_OSC_PATH)
        if cached is None:
            self.fetch_avatar_parameters()
            cached = self._param_cache.get(VRCHAT_OSC_PATH)
        if cached is None:
            cached = self._fetch_eyeheight_direct()
        if cached is None:
            return None
        try:
            return float(cached)
        except (TypeError, ValueError):
            return None

    def force_height_refresh(self) -> None:
        """Drop any cached eye height and re-arm the resolver loop so the
        next query goes to VRChat instead of returning a stale value.

        Public entry point for the UI's "↻ refresh" button — keeps the
        controller from having to poke the manager's private cache /
        resolver internals directly."""
        self._param_cache.pop(VRCHAT_OSC_PATH, None)
        try:
            self._start_eyeheight_resolver()
        except Exception as e:
            self._log(
                f"force_height_refresh: could not restart resolver: "
                f"{type(e).__name__}: {e}"
            )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def _start_health_check(self) -> None:
        if self._health_thread and self._health_thread.is_alive():
            return

        def loop() -> None:
            consecutive_failures = 0
            last_failure_kind = ""
            while not self._shutdown.is_set():
                if self._shutdown.wait(HEALTH_CHECK_INTERVAL_S):
                    return
                if not self.is_connected or not self.http_port:
                    consecutive_failures = 0
                    continue
                try:
                    response = requests.get(
                        f"http://127.0.0.1:{self.http_port}/", timeout=1.5
                    )
                    if response.status_code == 200:
                        if consecutive_failures > 0:
                            self._log(
                                f"health-check recovered after {consecutive_failures} "
                                f"failure(s) (last={last_failure_kind})"
                            )
                        consecutive_failures = 0
                        continue
                    consecutive_failures += 1
                    last_failure_kind = f"HTTP {response.status_code}"
                    self._log(
                        f"health-check non-200 from VRChat: {last_failure_kind} "
                        f"(consecutive={consecutive_failures})"
                    )
                except Exception as e:
                    consecutive_failures += 1
                    last_failure_kind = f"{type(e).__name__}: {e}"
                    if consecutive_failures <= 2:
                        self._log(
                            f"health-check exception: {last_failure_kind} "
                            f"(consecutive={consecutive_failures})"
                        )
                if consecutive_failures >= 2:
                    self._handle_disconnect(
                        f"OSCQuery HTTP unreachable ({last_failure_kind})"
                    )
                    consecutive_failures = 0

        self._health_thread = threading.Thread(target=loop, daemon=True, name="OSC-HealthCheck")
        self._health_thread.start()

    def _handle_disconnect(self, reason: str) -> None:
        # Compare-and-set under the lock so concurrent callers (health-check
        # thread + mDNS-removed handler) can't both pass the guard and fire
        # on_disconnected twice.
        with self._state_lock:
            if not self.is_connected:
                return
            self.is_connected = False
        try:
            session_s = (time.time() - self._connected_since) if self._connected_since else 0.0
            last_pkt_age = (
                f"{time.time() - self._last_packet_time:.1f}s ago"
                if self._last_packet_time else "never"
            )
            self._log(
                f"disconnecting (reason={reason}) — session={session_s:.1f}s "
                f"packets_handled={self._packets_handled} last_packet={last_pkt_age} "
                f"phonebook_GETs={self._phonebook_requests} "
                f"handler_exceptions={self._handler_exceptions}"
            )
        except Exception:
            pass
        self._connected_since = None
        self._silent_warning_logged = False
        self._silent_reprobe_attempted = False
        if self.on_disconnected:
            try:
                self.on_disconnected()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Diagnostics watchdog
    # ------------------------------------------------------------------

    def _start_diagnostics(self) -> None:
        if self._diag_thread and self._diag_thread.is_alive():
            return

        def loop() -> None:
            while not self._shutdown.is_set():
                if self._shutdown.wait(DIAG_LOG_INTERVAL_S):
                    return
                try:
                    self._emit_diagnostics_tick()
                except Exception as e:
                    logger.warning(f"diagnostics tick error: {type(e).__name__}: {e}")

        self._diag_thread = threading.Thread(target=loop, daemon=True, name="OSC-Diagnostics")
        self._diag_thread.start()

    def _emit_diagnostics_tick(self) -> None:
        now = time.time()
        handled_now = self._packets_handled
        delta = handled_now - self._packets_handled_at_last_log
        self._packets_handled_at_last_log = handled_now

        if not self.is_connected:
            return

        rate = delta / DIAG_LOG_INTERVAL_S
        last_pkt_age = (
            now - self._last_packet_time
            if self._last_packet_time is not None
            else (now - (self._connected_since or now))
        )
        self._log(
            f"diagnostics: pkts_last_{int(DIAG_LOG_INTERVAL_S)}s={delta} "
            f"({rate:.1f}/s) total={handled_now} last_packet={last_pkt_age:.1f}s ago "
            f"phonebook_GETs={self._phonebook_requests} "
            f"handler_exc={self._handler_exceptions}"
        )

        if self._connected_since is None or (now - self._connected_since) < 5.0:
            return

        silent_for = last_pkt_age
        if delta == 0 and silent_for >= SILENT_THRESHOLD_S:
            if not self._silent_warning_logged:
                self._silent_warning_logged = True
                self._log(
                    "WARNING: VRChat says connected but we've received 0 packets "
                    f"in the last {silent_for:.1f}s. Likely cause: another OSC app "
                    "(VRCOSC, OSCgoesBrrr, OscGoesPurrr, etc.) is also advertising "
                    "via OSCQuery and VRChat is routing to it instead. Try: VRChat "
                    "→ Settings → OSC → Reset, or close other OSC apps and reconnect."
                )
            if silent_for >= SILENT_REPROBE_S and not self._silent_reprobe_attempted:
                self._silent_reprobe_attempted = True
                self._log("attempting OSCQuery re-poll to nudge VRChat...")
                threading.Thread(
                    target=self._reprobe_silent_connection, daemon=True,
                    name="OSC-SilentReprobe",
                ).start()
            if silent_for >= SILENT_REREGISTER_S and not self._silent_rereg_attempted:
                self._silent_rereg_attempted = True
                self._log(
                    "silent for too long — re-publishing mDNS under a fresh name"
                )
                threading.Thread(
                    target=self.reregister_mdns, daemon=True,
                    name="OSC-SilentReregister",
                ).start()
        elif delta > 0 and self._silent_warning_logged:
            self._log(
                f"packet flow restored — received {delta} in the last "
                f"{int(DIAG_LOG_INTERVAL_S)}s"
            )
            self._silent_warning_logged = False
            self._silent_reprobe_attempted = False
            self._silent_rereg_attempted = False

    def _reprobe_silent_connection(self) -> None:
        try:
            if self.osc_server is not None and self.osc_server.socket is not None:
                ping = OscMessageBuilder(address=f"/{APP_NAME}/ping")
                ping.add_arg(True)
                self.osc_server.socket.sendto(
                    ping.build().dgram, (self.vrc_ip, self.vrc_osc_port)
                )
                self._log(
                    f"silent-reprobe: ping resent to {self.vrc_ip}:{self.vrc_osc_port}"
                )
        except Exception as e:
            self._log(f"silent-reprobe failed: {type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    # Incoming OSC dispatch
    # ------------------------------------------------------------------

    def _handle_incoming_osc(self, address: str, *args: Any) -> None:
        try:
            self._packets_handled += 1
            self._last_packet_time = time.time()
            if not self._first_packet_logged:
                self._first_packet_logged = True
                self._log(f"first OSC packet received this session: address={address!r}")

            # Cache the eye-height value (the only parameter anything ever
            # reads back) so an HTTP fallback / manual refresh reflects the
            # last value VRChat broadcast. We deliberately don't cache every
            # other incoming address: VRChat streams the whole avatar
            # parameter set, nothing consumes those keys, and storing them
            # would just grow the dict with entries we never look at.
            if args and address == VRCHAT_OSC_PATH:
                self._param_cache[address] = args[0] if len(args) == 1 else list(args)

            if address == VRCHAT_OSC_PATH and args:
                if self.on_height_received:
                    try:
                        self.on_height_received(float(args[0]))
                    except Exception as e:
                        self._log(f"on_height_received error: {type(e).__name__}: {e}")
            elif address == VRCHAT_AVATAR_CHANGE_PATH:
                avatar_id = str(args[0]) if args else ""
                self._log(f"/avatar/change received: value={avatar_id!r}")
                # Avatar changed → the cached tree is stale. Re-fetch in the
                # background so the next query reflects the new avatar.
                threading.Thread(
                    target=self._refetch_after_avatar_change,
                    daemon=True, name="OSC-AvatarRefetch",
                ).start()
                if self.on_avatar_change:
                    try:
                        self.on_avatar_change(avatar_id)
                    except Exception as e:
                        self._log(f"on_avatar_change error: {type(e).__name__}: {e}")
        except Exception as e:
            self._handler_exceptions += 1
            self._last_handler_error = f"{type(e).__name__}: {e}"
            if self._handler_exceptions <= 5:
                logger.error(
                    f"OSC handler exception ({self._handler_exceptions}): "
                    f"address={address!r} args={args!r} error={self._last_handler_error}"
                )

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send_height(self, height_cm: float) -> None:
        """Send a height in cm to VRChat (converted to metres)."""
        if not self.is_connected or self.osc_client is None:
            return
        meters = float(height_cm) / 100.0
        try:
            self.osc_client.send_message(VRCHAT_OSC_PATH, meters)
        except OSError as e:
            self._log(f"send_height OS error: {type(e).__name__}: {e}")
        except Exception as e:
            self._log(f"send_height error: {type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def ports(self) -> Dict[str, Any]:
        return {
            "target_ip": self.vrc_ip,
            "udp_send_port": self.vrc_osc_port,
            "http_oscquery_port": self.http_port,
            "local_listen_port": self.local_listen_port,
            "our_http_phonebook_port": self.http_listen_port,
            "is_connected": self.is_connected,
        }

    def get_diagnostics(self) -> Dict[str, Any]:
        now = time.time()
        last_pkt_age = (
            now - self._last_packet_time if self._last_packet_time is not None else None
        )
        session_age = (
            now - self._connected_since if self._connected_since is not None else None
        )
        return {
            "is_connected": self.is_connected,
            "packets_handled": self._packets_handled,
            "last_packet_age_s": last_pkt_age,
            "session_age_s": session_age,
            "phonebook_GETs": self._phonebook_requests,
            "handler_exceptions": self._handler_exceptions,
            "last_handler_error": self._last_handler_error,
            "vrc_ip": self.vrc_ip,
            "vrc_osc_port": self.vrc_osc_port,
            "vrc_http_port": self.http_port,
            "our_listen_port": self.local_listen_port,
            "our_http_phonebook_port": self.http_listen_port,
            "mdns_service_name": self.service_short_name,
            "mdns_rereg_count": self._mdns_rereg_count,
            "http_raw_connections": self._raw_http_connections,
            "log_file_path": self.get_log_file_path(),
        }
