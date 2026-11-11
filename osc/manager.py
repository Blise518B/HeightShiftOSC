"""
osc/manager.py — HeightShift's connection to VRChat (OSC + OSCQuery).

Transport only: it finds VRChat, keeps the connection healthy, passes on
what VRChat reports and sends what it is told. WHAT to send, WHEN, and
whether a reported height can be trusted is the controller's job.

  * Discovery, VRCFT-style: browse `_oscjson._tcp.local.`; no socket is
    opened and nothing is advertised until VRChat is on the bus.
  * Then bind the UDP listener and the OSCQuery phonebook (oscquery.py) on
    127.0.0.1 and advertise both under a per-launch name (HeightShift-AB12CD),
    so VRChat can't reuse a port it cached from an earlier run.
  * Connect: read VRChat's UDP port from its ?HOST_INFO and send the
    handshake ping from the listener's socket, so VRChat learns our port.
  * Receive: one thread handles packets in arrival order; /avatar/eyeheight
    and /avatar/change are passed on with the time they arrived.
  * Read: read_height() asks VRChat's OSCQuery server for /avatar/eyeheight,
    stamped with the time the request was MADE.
  * Leave: VRChat's mDNS record going away, its HTTP server not answering
    twice in a row, or VRChat restarting (a new instance answers, ours
    doesn't) disconnects. A leftover record of a dead VRChat is ignored, and
    nothing about another record can drop the connection we have.
  * Diagnostics: osc_diagnostics.log (diag_log.py), and a watchdog that
    re-pings / re-advertises a connection that looks alive but gets nothing.

Same handshake, sockets, naming and in-order UDP server as OscGoesPurrr's
vrchat_osc.py.
"""

from __future__ import annotations

import logging
import os
import random
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.udp_client import SimpleUDPClient
from zeroconf import ServiceBrowser, ServiceInfo, ServiceStateChange, Zeroconf

from constants import (
    APP_NAME,
    BROWSER_REFRESH_S,
    DIAG_LOG_INTERVAL_S,
    HEALTH_CHECK_INTERVAL_S,
    LOG_FILE_MAX_BYTES,
    LOG_FILE_NAME,
    MENU_PREFIX,
    SILENT_REPROBE_S,
    SILENT_REREGISTER_S,
    SILENT_RETRY_INTERVAL_S,
    SILENT_THRESHOLD_S,
    VRC_DEFAULT_PORT,
    VRCHAT_AVATAR_CHANGE_PATH,
    VRCHAT_HTTP_TIMEOUT,
    VRCHAT_OSC_PATH,
)

from .diag_log import DiagLog

PARAMETERS = "/avatar/parameters/"
MENU_ADDRESS = PARAMETERS + MENU_PREFIX          # /avatar/parameters/HeightShift/
# VRChat's own, for every avatar, read-only: current eye height / the
# avatar's default eye height (so its default = current / ScaleFactor)
SCALE_FACTOR = PARAMETERS + "ScaleFactor"


class _UdpReceiver:
    """The OSC listener: one socket, one thread, packets in arrival order.

    A plain recvfrom loop, not socketserver's: that built a handler object
    and ran select() for every datagram — at VRChat's ~2,900 a second, most
    of the idle cost even with the packets dropped undecoded (_WantedOnly).
    Same surface as the server it replaces: socket, server_address,
    serve_forever, shutdown, server_close."""

    def __init__(self, address, dispatcher: Dispatcher) -> None:
        self.dispatcher = dispatcher
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # room for a burst while the thread is busy
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        except OSError:
            pass
        self.socket.bind(address)
        self.socket.settimeout(0.5)            # to notice shutdown
        self.server_address = self.socket.getsockname()
        self._stop = threading.Event()

    def serve_forever(self) -> None:
        recv = self.socket.recvfrom
        handle = self.dispatcher.call_handlers_for_packet
        while not self._stop.is_set():
            try:
                data, addr = recv(65536)
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                continue                       # e.g. Windows' ICMP "port unreachable"
            try:
                handle(data, addr)
            except Exception:
                pass                           # one bad packet never stops the loop

    def shutdown(self) -> None:
        self._stop.set()

    def server_close(self) -> None:
        self._stop.set()
        try:
            self.socket.close()
        except OSError:
            pass


class _WantedOnly(Dispatcher):
    """Decodes only the packets HeightShift reads.

    VRChat streams every avatar parameter to every OSCQuery client that
    lists an /avatar node — measured 2026-11-11 with face tracking: ~2,900
    packets a second, and decoding all of them in Python cost ~10 % of a
    core while the app sat idle. An OSC packet starts with its address, so
    a few bytes decide: the four addresses below are handed on, everything
    else is only counted (it still shows VRChat is talking — the health
    check's "silent" watch) and dropped undecoded."""

    WANTED = (VRCHAT_OSC_PATH.encode() + b"\0", VRCHAT_AVATAR_CHANGE_PATH.encode() + b"\0",
              MENU_ADDRESS.encode(), SCALE_FACTOR.encode() + b"\0", b"#bundle")

    def __init__(self, seen) -> None:
        super().__init__()
        self._seen = seen

    def call_handlers_for_packet(self, data, client_address):
        if data.startswith(self.WANTED):
            return super().call_handlers_for_packet(data, client_address)
        self._seen()
        return []
from .oscquery import LOOPBACK, PhonebookServer, host_info, node_value, tree

logger = logging.getLogger(__name__)

OSCJSON_TYPE = "_oscjson._tcp.local."
OSC_TYPE = "_osc._udp.local."

_SUFFIX_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def make_service_name(base: str = APP_NAME) -> str:
    """`HeightShift-AB12CD`, VRCFT's shape (6 uppercase alphanumerics). A new
    one per launch and per re-advertisement."""
    return base + "-" + "".join(random.choice(_SUFFIX_CHARS) for _ in range(6))


def is_vrchat_service(name: str) -> bool:
    """VRChat advertises itself as `VRChat-Client-XXXXXX._oscjson._tcp.local.`
    (the only VRChat name in months of logs). The prefix, not "VRChat"
    anywhere in the name: another OSC app called e.g. "VRChatTool" must not
    be mistaken for the game."""
    return name.startswith("VRChat-Client-")


class VRChatOSCManager:
    """See the module docstring. Callbacks run on background threads."""

    def __init__(self, log_dir: Optional[str] = None,
                 clock: Callable[[], float] = time.perf_counter):
        # Every time stamp handed to a callback comes from this clock, so the
        # controller can compare them with its own.
        self._clock = clock
        self._diag = DiagLog(os.path.join(log_dir, LOG_FILE_NAME) if log_dir else None,
                             LOG_FILE_MAX_BYTES)

        self.on_connected: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_disconnected: Optional[Callable[[], None]] = None
        self.on_height_received: Optional[Callable[[float, float], None]] = None  # m, seen at
        self.on_avatar_change: Optional[Callable[[str, float], None]] = None      # id, seen at
        # HeightShift's own menu parameters (constants.MENU_*): name, value, seen at
        self.on_menu_parameter: Optional[Callable[[str, Any, float], None]] = None
        # VRChat's ScaleFactor (see SCALE_FACTOR): value, seen at
        self.on_scale_factor: Optional[Callable[[float, float], None]] = None

        # --- VRChat ---
        self.vrc_ip = LOOPBACK                 # always: every socket here is loopback-only
        self.vrc_osc_port = VRC_DEFAULT_PORT   # where VRChat receives (from its HOST_INFO)
        self.http_port: Optional[int] = None   # VRChat's OSCQuery HTTP server
        self._vrchat_name: Optional[str] = None  # the mDNS record we're connected to
        self.is_connected = False
        self._state_lock = threading.Lock()

        # --- us ---
        self.local_listen_port = 0
        self.osc_server: Optional[_UdpReceiver] = None
        self.osc_client: Optional[SimpleUDPClient] = None
        self.phonebook: Optional[PhonebookServer] = None
        self.service_name = make_service_name()
        self._advertised: List[ServiceInfo] = []
        self._sockets_open = False
        self._setup_lock = threading.Lock()
        self.dispatcher = _WantedOnly(self._note_packet)
        self.dispatcher.set_default_handler(self._handle_incoming_osc)

        # --- discovery ---
        self.zeroconf: Optional[Zeroconf] = None
        self.browser: Optional[ServiceBrowser] = None
        self._services_seen: set = set()       # for logging each one once
        self._shutdown = threading.Event()

        # --- diagnostics (plain writes; a stale read only skews a log line) ---
        self._connected_since: Optional[float] = None    # time.monotonic()
        self._last_packet_time: Optional[float] = None   # time.monotonic()
        self._packets_handled = 0
        self._packets_at_last_tick = 0
        self._handler_errors = 0
        self._first_packet_logged = False
        self._phonebook_requests = 0
        self._readvertise_count = 0
        self._silent_warned = False
        self._last_reping: Optional[float] = None
        self._last_readvertise: Optional[float] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start looking for VRChat; the sockets open once it is found."""
        self._shutdown.clear()
        self.zeroconf = Zeroconf()
        self._log(f"start: looking for VRChat on {OSCJSON_TYPE} "
                  "(our sockets open once it is found)")
        self.browser = self._new_browser()
        for target, name in ((self._mdns_refresh_loop, "OSC-mDNSRefresh"),
                             (self._health_loop, "OSC-HealthCheck"),
                             (self._diagnostics_loop, "OSC-Diagnostics")):
            threading.Thread(target=target, daemon=True, name=name).start()

    def stop(self) -> None:
        self._shutdown.set()
        with self._state_lock:
            self.is_connected = False
        zc, self.zeroconf = self.zeroconf, None
        if zc is not None:
            try:
                zc.unregister_all_services()      # VRChat sees us leave cleanly
            except Exception:
                pass
            try:
                zc.close()
            except Exception:
                pass
        self._close_sockets()

    @property
    def ports(self) -> Dict[str, Any]:
        return {
            "target_ip": self.vrc_ip,
            "udp_send_port": self.vrc_osc_port,
            "http_oscquery_port": self.http_port,
            "local_listen_port": self.local_listen_port,
            "our_http_phonebook_port": self.phonebook.port if self.phonebook else None,
            "is_connected": self.is_connected,
        }

    def _log(self, message: str) -> None:
        logger.info(message)
        self._diag.write(message)

    # ------------------------------------------------------------------
    # Finding VRChat (mDNS)
    # ------------------------------------------------------------------

    def _new_browser(self) -> ServiceBrowser:
        return ServiceBrowser(self.zeroconf, OSCJSON_TYPE,
                              handlers=[self._on_service_state_change])

    def _mdns_refresh_loop(self) -> None:
        """While disconnected, rebuild the browser every BROWSER_REFRESH_S so
        the bus is asked again (VRCOSC's refreshServices). Recovers from a
        VRChat announcement missed at our startup, and retries a connection
        attempt that failed."""
        cycles = 0
        while not self._shutdown.wait(BROWSER_REFRESH_S):
            if self.is_connected:
                cycles = 0
                continue
            cycles += 1
            try:
                old = self.browser
                if old is not None:
                    old.cancel()
                if self.zeroconf is None:
                    return
                self.browser = self._new_browser()
                if cycles == 1 or cycles % 6 == 0:
                    self._log(f"mDNS browser refreshed (#{cycles}) — still waiting for VRChat")
            except Exception as e:
                if cycles <= 3:
                    self._log(f"mDNS refresh failed: {type(e).__name__}: {e}")

    def _on_service_state_change(self, zeroconf: Zeroconf, service_type: str, name: str,
                                 state_change: ServiceStateChange) -> None:
        if state_change == ServiceStateChange.Updated:
            return
        # Other OSC apps coming and going is what to correlate a broken
        # connection with, so they are logged too — once each: the browser
        # rebuilt every few seconds re-reports everything still there.
        if state_change == ServiceStateChange.Added:
            if name not in self._services_seen:
                self._services_seen.add(name)
                self._log(f"mDNS Added: {name}")
        else:
            self._services_seen.discard(name)
            self._log(f"mDNS {state_change.name}: {name}")
        if not is_vrchat_service(name):
            return
        if state_change == ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info is None or not info.port:
                self._log(f"{name} had no port yet — waiting for its next announcement")
                return
            self._on_vrchat_found(name, info.port)
        elif state_change == ServiceStateChange.Removed:
            self._handle_disconnect("VRChat's mDNS record was removed", only_name=name)

    def _on_vrchat_found(self, name: str, http_port: int) -> None:
        if self._shutdown.is_set() or not self._ensure_sockets():
            return
        with self._state_lock:
            same = (self.is_connected and name == self._vrchat_name
                    and http_port == self.http_port)
            replaced = self.is_connected and not same
        if same:
            return                     # a repeated announcement of the VRChat we talk to
        if replaced:
            # A second VRChat record while connected. A crashed VRChat's
            # record can linger for hours: OscGoesPurrr's log shows a dead
            # VRChat-Client-305E19 next to the live game for 1.7 h, and
            # switching to it dropped the working connection 125 times. So
            # switch only when the new one answers and ours no longer does
            # (VRChat crashed and came back faster than the health check).
            current = self.http_port
            if not self._vrchat_answers(http_port):
                self._log(f"ignoring {name}: its OSCQuery server doesn't answer "
                          "(a record left over from an earlier VRChat?)")
                return
            if current and self._vrchat_answers(current):
                self._log(f"ignoring {name}: still connected to {self._vrchat_name}, "
                          "which answers")
                return
            # Everything known about the old instance is stale — the avatar's
            # height first of all — so disconnect before connecting.
            self._handle_disconnect(f"VRChat was restarted ({name})", only_port=current)
        self._log(f"VRChat found: {name}, OSCQuery on HTTP port {http_port}")
        self._connect(name, http_port)

    # ------------------------------------------------------------------
    # Our sockets and advertisement
    # ------------------------------------------------------------------

    def _ensure_sockets(self) -> bool:
        """Open the UDP listener + phonebook and advertise them, once, the
        first time VRChat is seen (VRCFT's FirstClientDiscovered). Later VRChat
        appearances reuse them."""
        with self._setup_lock:
            if self._sockets_open:
                return True
            try:
                self._open_sockets()
            except Exception as e:
                self._log(f"could not open the OSC sockets: {type(e).__name__}: {e}")
                self._close_sockets()
                return False
            self._sockets_open = True
            return True

    def _open_sockets(self) -> None:
        # One thread, packets handled in arrival order. The threading server
        # spawned a thread per datagram — VRChat streams every avatar
        # parameter, hundreds a second with face tracking — and two eye
        # heights could then be handled in the wrong order.
        server = _UdpReceiver((LOOPBACK, 0), self.dispatcher)
        self.osc_server = server
        self.local_listen_port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True,
                         name="OSC-UDPServer").start()
        self._log(f"OSC listener on {LOOPBACK}:{self.local_listen_port}")

        self.phonebook = PhonebookServer(
            host_info(APP_NAME, self.local_listen_port),
            tree(APP_NAME, self.local_listen_port, VRCHAT_OSC_PATH, VRCHAT_AVATAR_CHANGE_PATH),
            on_request=self._on_phonebook_request)
        self._log(f"OSCQuery phonebook on {LOOPBACK}:{self.phonebook.port}")
        self._advertise()

    @staticmethod
    def _close_client(client: Optional[SimpleUDPClient]) -> None:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    def _close_sockets(self) -> None:
        client, self.osc_client = self.osc_client, None
        self._close_client(client)
        server, self.osc_server = self.osc_server, None
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass
            try:
                server.server_close()
            except Exception:
                pass
        phonebook, self.phonebook = self.phonebook, None
        if phonebook is not None:
            try:
                phonebook.stop()
            except Exception:
                pass
        self._sockets_open = False

    def _advertise(self) -> None:
        """Publish `_osc._udp` (the listener) and `_oscjson._tcp` (the
        phonebook), both at 127.0.0.1, under self.service_name."""
        zc, phonebook = self.zeroconf, self.phonebook
        if zc is None or phonebook is None:
            return
        host = f"{self.service_name}.local."
        for service_type, port in ((OSC_TYPE, self.local_listen_port),
                                   (OSCJSON_TYPE, phonebook.port)):
            info = ServiceInfo(service_type, f"{self.service_name}.{service_type}",
                               addresses=[socket.inet_aton(LOOPBACK)], port=port,
                               properties={"version": b"1.0"}, server=host)
            try:
                zc.register_service(info)
                self._advertised.append(info)
                self._log(f"mDNS advertised {info.name} -> {LOOPBACK}:{port}")
            except Exception as e:
                self._log(f"mDNS advertise FAILED for {info.name}: {type(e).__name__}: {e}")

    def reregister_mdns(self) -> bool:
        """Withdraw our advertisement and publish it again under a fresh
        name, so VRChat treats us as a new client and reads our phonebook again."""
        zc = self.zeroconf
        if zc is None or not self._sockets_open:
            return False
        self._readvertise_count += 1
        old = self.service_name
        for info in self._advertised:
            try:
                zc.unregister_service(info)
            except Exception as e:
                self._log(f"mDNS withdraw of {info.name} failed: {type(e).__name__}: {e}")
        self._advertised = []
        self.service_name = make_service_name()
        self._log(f"re-advertising as {self.service_name} (was {old}, "
                  f"#{self._readvertise_count})")
        time.sleep(0.5)                # let the withdrawal reach the bus first
        self._advertise()
        return True

    def _on_phonebook_request(self, path: str, client: str) -> None:
        self._phonebook_requests += 1
        if self._phonebook_requests <= 3:
            self._log(f"phonebook read #{self._phonebook_requests}: {path} from {client}")

    # ------------------------------------------------------------------
    # Connecting and leaving
    # ------------------------------------------------------------------

    def _connect(self, name: str, http_port: int) -> None:
        osc_port = self._read_vrchat_osc_port(http_port)
        if osc_port is None:
            # VRChat's HTTP server isn't answering yet. Stay disconnected: the
            # refresh loop asks the bus again in a few seconds.
            return
        with self._state_lock:
            if self._shutdown.is_set() or self.osc_server is None:
                return
            self.http_port = http_port
            self._vrchat_name = name
            self.vrc_osc_port = osc_port
            old_client, self.osc_client = self.osc_client, SimpleUDPClient(LOOPBACK, osc_port)
            self.is_connected = True
        self._close_client(old_client)
        self._connected_since = time.monotonic()
        self._first_packet_logged = False
        self._reset_watchdog()
        self._send_ping()
        self._log(f"connected: VRChat receives on UDP {osc_port}, "
                  f"we listen on UDP {self.local_listen_port}")
        cb = self.on_connected
        if cb is not None:
            try:
                cb(self.ports)
            except Exception as e:
                self._log(f"on_connected failed: {type(e).__name__}: {e}")

    def _read_vrchat_osc_port(self, http_port: int) -> Optional[int]:
        """VRChat's UDP port from its ?HOST_INFO (the OSCQuery place for it);
        None while VRChat's HTTP server doesn't answer."""
        url = f"http://{LOOPBACK}:{http_port}/?HOST_INFO"
        try:
            r = requests.get(url, timeout=VRCHAT_HTTP_TIMEOUT)
            data = r.json() if r.status_code == 200 else None
        except Exception as e:
            self._log(f"VRChat's HOST_INFO didn't answer ({type(e).__name__}) — trying again soon")
            return None
        if data is None:
            self._log(f"VRChat's HOST_INFO answered HTTP {r.status_code} — trying again soon")
            return None
        try:
            port = int(data.get("OSC_PORT"))
            if 0 < port < 65536:
                return port
        except (AttributeError, TypeError, ValueError):
            pass
        self._log(f"VRChat's HOST_INFO has no usable OSC_PORT — using {VRC_DEFAULT_PORT}")
        return VRC_DEFAULT_PORT

    @staticmethod
    def _vrchat_answers(http_port: int) -> bool:
        try:
            return requests.get(f"http://{LOOPBACK}:{http_port}/",
                                timeout=1.5).status_code == 200
        except Exception:
            return False

    def _send_ping(self) -> None:
        """The handshake: a packet sent from the LISTENER's socket, so VRChat
        sees the exact port we receive on (not a throwaway send port)."""
        server = self.osc_server
        if server is None:
            return
        msg = OscMessageBuilder(address=f"/{APP_NAME}/ping")
        msg.add_arg(True)
        try:
            server.socket.sendto(msg.build().dgram, (LOOPBACK, self.vrc_osc_port))
        except OSError as e:
            self._log(f"handshake ping failed: {e}")

    def _health_loop(self) -> None:
        """While connected, poll VRChat's OSCQuery server: catches a VRChat
        that crashed or was killed (its mDNS record never says goodbye then).
        Two misses in a row disconnect; one stray timeout on a busy PC doesn't."""
        misses = 0
        while not self._shutdown.wait(HEALTH_CHECK_INTERVAL_S):
            port = self.http_port
            if not self.is_connected or not port:
                misses = 0
                continue
            try:
                status = requests.get(f"http://{LOOPBACK}:{port}/", timeout=1.5).status_code
                why = "" if status == 200 else f"HTTP {status}"
            except Exception as e:
                why = type(e).__name__
            if not why:
                if misses:
                    self._log(f"VRChat's OSCQuery server answers again after {misses} miss(es)")
                misses = 0
                continue
            misses += 1
            if misses <= 2:
                self._log(f"VRChat's OSCQuery server didn't answer ({why}), miss {misses}")
            if misses >= 2:
                self._handle_disconnect(f"VRChat's OSCQuery server stopped answering ({why})",
                                        only_port=port)
                misses = 0

    def _handle_disconnect(self, reason: str, *, only_name: Optional[str] = None,
                           only_port: Optional[int] = None) -> None:
        """Flip to disconnected and tell the controller — once. `only_name` /
        `only_port` make it apply only to the VRChat instance the caller saw,
        so news about an old instance can't drop a newer connection."""
        with self._state_lock:
            if not self.is_connected:
                return
            if only_name is not None and only_name != self._vrchat_name:
                return
            if only_port is not None and only_port != self.http_port:
                return
            self.is_connected = False
            self._vrchat_name = None
        since = self._connected_since
        session = time.monotonic() - since if since is not None else 0.0
        last = self._last_packet_time
        last_text = f"{time.monotonic() - last:.1f}s ago" if last is not None else "never"
        self._log(f"disconnected ({reason}) after {session:.0f}s — "
                  f"{self._packets_handled} packets, last {last_text}, "
                  f"phonebook reads {self._phonebook_requests}, "
                  f"handler errors {self._handler_errors}")
        self._connected_since = None
        self._reset_watchdog()
        cb = self.on_disconnected
        if cb is not None:
            try:
                cb()
            except Exception as e:
                self._log(f"on_disconnected failed: {type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    # Watchdog: connected, but nothing arrives
    # ------------------------------------------------------------------

    def _reset_watchdog(self) -> None:
        self._silent_warned = False
        self._last_reping = None
        self._last_readvertise = None

    def _diagnostics_loop(self) -> None:
        while not self._shutdown.wait(DIAG_LOG_INTERVAL_S):
            try:
                self._diagnostics_tick(time.monotonic())
            except Exception as e:
                logger.warning(f"diagnostics tick failed: {type(e).__name__}: {e}")

    def _diagnostics_tick(self, now: float) -> None:
        """Log the packet rate. If the connection looks alive but nothing
        arrives, try the cheap fix (ping again) and then the strong one
        (re-advertise under a new name), again every SILENT_RETRY_INTERVAL_S
        while it stays silent."""
        total = self._packets_handled
        delta, self._packets_at_last_tick = total - self._packets_at_last_tick, total
        since = self._connected_since
        if not self.is_connected or since is None:
            return
        last = self._last_packet_time
        silent_for = now - (last if last is not None and last > since else since)
        self._log(f"diagnostics: {delta} packets in the last {DIAG_LOG_INTERVAL_S:.0f}s, "
                  f"last {silent_for:.1f}s ago, phonebook reads {self._phonebook_requests}, "
                  f"handler errors {self._handler_errors}")
        if now - since < 5.0:
            return
        if delta > 0:
            if self._silent_warned:
                self._log("packets are arriving again")
                self._reset_watchdog()
            return
        if silent_for < SILENT_THRESHOLD_S:
            return
        if not self._silent_warned:
            self._silent_warned = True
            self._log(f"WARNING: connected, but nothing received for {silent_for:.0f}s. "
                      "VRChat's mDNS listener may have died (restart VRChat), or another "
                      "OSC app gets VRChat's data instead (VRChat → Settings → OSC → Reset).")

        def due(previous: Optional[float]) -> bool:
            return previous is None or now - previous >= SILENT_RETRY_INTERVAL_S

        if silent_for >= SILENT_REPROBE_S and due(self._last_reping):
            self._last_reping = now
            self._log("sending the handshake ping again")
            self._send_ping()
        if silent_for >= SILENT_REREGISTER_S and due(self._last_readvertise):
            self._last_readvertise = now
            threading.Thread(target=self.reregister_mdns, daemon=True,
                             name="OSC-Readvertise").start()

    # ------------------------------------------------------------------
    # Receiving, reading, sending
    # ------------------------------------------------------------------

    def _note_packet(self) -> None:
        """A packet HeightShift doesn't read: it only counts (cheap)."""
        self._packets_handled += 1
        self._last_packet_time = time.monotonic()

    def _handle_incoming_osc(self, address: str, *args: Any) -> None:
        seen_at = self._clock()
        try:
            self._packets_handled += 1
            self._last_packet_time = time.monotonic()
            if not self._first_packet_logged:
                self._first_packet_logged = True
                self._log(f"first OSC packet this session: {address}")
            if address == VRCHAT_OSC_PATH and args:
                cb = self.on_height_received
                if cb is not None:
                    cb(float(args[0]), seen_at)
            elif address == VRCHAT_AVATAR_CHANGE_PATH:
                avatar_id = str(args[0]) if args else ""
                self._log(f"/avatar/change: {avatar_id}")
                cb = self.on_avatar_change
                if cb is not None:
                    cb(avatar_id, seen_at)
            elif address.startswith(MENU_ADDRESS) and args:
                cb = self.on_menu_parameter
                if cb is not None:
                    cb(address[len(PARAMETERS):], args[0], seen_at)
            elif address == SCALE_FACTOR and args:
                cb = self.on_scale_factor
                if cb is not None:
                    cb(float(args[0]), seen_at)
        except Exception as e:
            # Never let one bad packet stop the receive thread.
            self._handler_errors += 1
            if self._handler_errors <= 5:
                self._log(f"OSC handler error #{self._handler_errors} for {address} "
                          f"{args!r}: {type(e).__name__}: {e}")

    def read_height(self) -> Optional[Tuple[float, float]]:
        """Ask VRChat for the avatar's eye height: (metres, asked_at) or None.

        `asked_at` is when the request was MADE: the answer describes the
        avatar at that moment or later, never earlier. Stamped with the
        arrival time instead, a slow answer looked newer than a height sent
        while it was on its way, and could replace it."""
        port = self.http_port
        if not self.is_connected or not port:
            return None
        asked_at = self._clock()
        try:
            r = requests.get(f"http://{LOOPBACK}:{port}{VRCHAT_OSC_PATH}",
                             timeout=VRCHAT_HTTP_TIMEOUT)
            if r.status_code != 200:
                self._log(f"GET {VRCHAT_OSC_PATH}: HTTP {r.status_code} {r.text[:200]!r}")
                return None
            meters = float(node_value(r.json()))
        except Exception as e:          # network, JSON, no / non-numeric VALUE
            self._log(f"GET {VRCHAT_OSC_PATH} failed: {type(e).__name__}: {e}")
            return None
        self._log(f"GET {VRCHAT_OSC_PATH} = {meters} m")
        return meters, asked_at

    def read_scale_factor(self) -> Optional[float]:
        """Ask VRChat's OSCQuery tree for the avatar's ScaleFactor (it is only
        sent when it changes): the value, or None when it couldn't be read."""
        port = self.http_port
        if not self.is_connected or not port:
            return None
        try:
            r = requests.get(f"http://{LOOPBACK}:{port}{SCALE_FACTOR}",
                             timeout=VRCHAT_HTTP_TIMEOUT)
            if r.status_code != 200:
                self._log(f"GET {SCALE_FACTOR}: HTTP {r.status_code}")
                return None
            value = float(node_value(r.json()))
        except Exception as e:
            self._log(f"GET {SCALE_FACTOR} failed: {type(e).__name__}: {e}")
            return None
        self._log(f"GET {SCALE_FACTOR} = {value}")
        return value

    def has_menu(self) -> Optional[bool]:
        """Does the avatar in VRChat have HeightShift's menu? Asks VRChat's
        OSCQuery tree for /avatar/parameters/HeightShift: True / False, or
        None when VRChat couldn't be asked."""
        port = self.http_port
        if not self.is_connected or not port:
            return None
        path = MENU_ADDRESS.rstrip("/")
        try:
            r = requests.get(f"http://{LOOPBACK}:{port}{path}", timeout=VRCHAT_HTTP_TIMEOUT)
        except Exception as e:
            self._log(f"GET {path} failed: {type(e).__name__}: {e}")
            return None
        if r.status_code == 404:
            return False
        if r.status_code != 200:
            self._log(f"GET {path}: HTTP {r.status_code} {r.text[:200]!r}")
            return None
        try:
            return bool(r.json().get("CONTENTS"))
        except Exception:
            return None

    def send_height(self, height_cm: float) -> bool:
        """Send a height in cm (as metres). True only if the packet left. No
        validation here: the controller's _write() is the single gate."""
        client = self.osc_client
        if not self.is_connected or client is None:
            return False
        try:
            client.send_message(VRCHAT_OSC_PATH, float(height_cm) / 100.0)
            return True
        except Exception as e:
            self._log(f"send failed: {type(e).__name__}: {e}")
            return False
