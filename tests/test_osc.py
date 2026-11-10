"""The OSC layer without VRChat: what we serve over OSCQuery, the handshake,
how packets and reads are passed on (with which time stamps), and which
events end a connection. A small fake of VRChat's OSCQuery HTTP server and
UDP port stands in for the game."""

import json
import socket
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

from pythonosc.osc_message import OscMessage
from pythonosc.udp_client import SimpleUDPClient

from constants import VRC_DEFAULT_PORT, VRCHAT_AVATAR_CHANGE_PATH, VRCHAT_OSC_PATH
from osc import oscquery
from osc.manager import VRChatOSCManager, is_vrchat_service, make_service_name

EYEHEIGHT_NODE = {"DESCRIPTION": "The current eye height of the avatar in meters.",
                  "FULL_PATH": "/avatar/eyeheight", "ACCESS": 3, "TYPE": "f",
                  "VALUE": [1.29905224]}       # as VRChat answers (from a real log)


class Clock:
    def __init__(self, start=100.0):
        self.t = start

    def __call__(self):
        self.t += 1.0
        return self.t


def get_json(url):
    with urllib.request.urlopen(url, timeout=2) as r:
        return r.status, json.loads(r.read())


class FakeVRChat:
    """VRChat's OSCQuery HTTP server, as far as HeightShift uses it."""

    def __init__(self, routes):
        self.routes = routes                      # raw path -> (status, body)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                status, body = outer.routes.get(self.path, (404, {"error": "not found"}))
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def connected_manager(http_port, name="VRChat-Client-AAAAAA"):
    mgr = VRChatOSCManager(log_dir=None, clock=Clock())
    mgr.is_connected = True
    mgr.http_port = http_port
    mgr._vrchat_name = name
    return mgr


# ----------------------------------------------------------------------
# What we serve
# ----------------------------------------------------------------------

class TestOSCQueryDocuments(unittest.TestCase):
    def test_host_info_points_at_our_udp_listener(self):
        doc = oscquery.host_info("HeightShift", 50123)
        self.assertEqual(doc["NAME"], "HeightShift")
        self.assertEqual((doc["OSC_IP"], doc["OSC_PORT"], doc["OSC_TRANSPORT"]),
                         ("127.0.0.1", 50123, "UDP"))
        self.assertNotIn("CONTENTS", doc)

    def test_tree_lists_eyeheight_and_change(self):
        doc = oscquery.tree("HeightShift", 50123, VRCHAT_OSC_PATH, VRCHAT_AVATAR_CHANGE_PATH)
        nodes = doc["CONTENTS"]["avatar"]["CONTENTS"]
        self.assertEqual(nodes["eyeheight"]["FULL_PATH"], "/avatar/eyeheight")
        self.assertEqual(nodes["change"]["FULL_PATH"], "/avatar/change")

    def test_node_value_unwraps_vrchats_list(self):
        self.assertEqual(oscquery.node_value(EYEHEIGHT_NODE), 1.29905224)
        self.assertEqual(oscquery.node_value({"VALUE": 2.0}), 2.0)
        self.assertIsNone(oscquery.node_value({"FULL_PATH": "/avatar"}))
        self.assertIsNone(oscquery.node_value({"VALUE": []}))
        self.assertIsNone(oscquery.node_value(None))


class TestPhonebookServer(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.info = oscquery.host_info("HeightShift", 50123)
        self.tree = oscquery.tree("HeightShift", 50123, VRCHAT_OSC_PATH,
                                  VRCHAT_AVATAR_CHANGE_PATH)
        self.server = oscquery.PhonebookServer(
            self.info, self.tree, on_request=lambda path, _c: self.requests.append(path))
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.stop()

    def test_host_info_gets_host_info_not_the_tree(self):
        # Answering this with the tree is the "connected but 0 packets" bug.
        self.assertEqual(get_json(self.base + "/?HOST_INFO"), (200, self.info))
        self.assertEqual(get_json(self.base + "/HOST_INFO"), (200, self.info))

    def test_root_gets_the_tree(self):
        self.assertEqual(get_json(self.base + "/"), (200, self.tree))

    def test_other_paths_are_404(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            get_json(self.base + "/avatar/eyeheight")
        self.assertEqual(cm.exception.code, 404)

    def test_requests_are_counted(self):
        get_json(self.base + "/?HOST_INFO")
        self.assertEqual(self.requests, ["/?HOST_INFO"])


# ----------------------------------------------------------------------
# Receiving
# ----------------------------------------------------------------------

class TestReceive(unittest.TestCase):
    def setUp(self):
        self.mgr = VRChatOSCManager(log_dir=None, clock=Clock())
        self.heights, self.changes = [], []
        self.mgr.on_height_received = lambda m, t: self.heights.append((m, t))
        self.mgr.on_avatar_change = lambda a, t: self.changes.append((a, t))

    def test_eyeheight_is_passed_on_with_its_arrival_time(self):
        self.mgr._handle_incoming_osc(VRCHAT_OSC_PATH, 1.6)
        self.assertEqual(self.heights, [(1.6, 101.0)])

    def test_avatar_change_is_passed_on(self):
        self.mgr._handle_incoming_osc(VRCHAT_AVATAR_CHANGE_PATH, "avtr_123")
        self.assertEqual(self.changes, [("avtr_123", 101.0)])

    def test_other_addresses_are_ignored(self):
        self.mgr._handle_incoming_osc("/avatar/parameters/Upright", 0.5)
        self.assertEqual((self.heights, self.changes), ([], []))

    def test_a_bad_packet_is_counted_not_raised(self):
        self.mgr._handle_incoming_osc(VRCHAT_OSC_PATH, "not a number")
        self.assertEqual(self.heights, [])
        self.assertEqual(self.mgr._handler_errors, 1)


# ----------------------------------------------------------------------
# Talking to VRChat's OSCQuery server
# ----------------------------------------------------------------------

class TestVRChatHTTP(unittest.TestCase):
    def tearDown(self):
        fake = getattr(self, "fake", None)
        if fake is not None:
            fake.close()

    def serve(self, routes):
        self.fake = FakeVRChat(routes)
        return self.fake.port

    def test_osc_port_comes_from_host_info(self):
        port = self.serve({"/?HOST_INFO": (200, {"NAME": "VRChat-Client-AAAAAA",
                                                 "OSC_IP": "127.0.0.1", "OSC_PORT": 9001})})
        self.assertEqual(VRChatOSCManager()._read_vrchat_osc_port(port), 9001)

    def test_host_info_without_a_port_falls_back_to_9000(self):
        port = self.serve({"/?HOST_INFO": (200, {"NAME": "VRChat-Client-AAAAAA"})})
        self.assertEqual(VRChatOSCManager()._read_vrchat_osc_port(port), VRC_DEFAULT_PORT)

    def test_unreachable_host_info_means_not_connected_yet(self):
        port = self.serve({})
        self.fake.close()
        self.fake = None
        self.assertIsNone(VRChatOSCManager()._read_vrchat_osc_port(port))

    def test_read_height_is_stamped_when_asked(self):
        port = self.serve({VRCHAT_OSC_PATH: (200, EYEHEIGHT_NODE)})
        mgr = connected_manager(port)
        self.assertEqual(mgr.read_height(), (1.29905224, 101.0))

    def test_read_height_without_a_value_is_none(self):
        port = self.serve({VRCHAT_OSC_PATH: (200, {"FULL_PATH": "/avatar/eyeheight"})})
        self.assertIsNone(connected_manager(port).read_height())

    def test_read_height_404_is_none(self):
        port = self.serve({})
        self.assertIsNone(connected_manager(port).read_height())

    def test_read_height_needs_a_connection(self):
        port = self.serve({VRCHAT_OSC_PATH: (200, EYEHEIGHT_NODE)})
        mgr = connected_manager(port)
        mgr.is_connected = False
        self.assertIsNone(mgr.read_height())


# ----------------------------------------------------------------------
# The whole handshake against a fake VRChat (real sockets, no mDNS)
# ----------------------------------------------------------------------

class TestHandshake(unittest.TestCase):
    def setUp(self):
        self.vrchat_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.vrchat_udp.bind(("127.0.0.1", 0))
        self.vrchat_udp.settimeout(2.0)
        udp_port = self.vrchat_udp.getsockname()[1]
        self.fake = FakeVRChat({"/?HOST_INFO": (200, {"OSC_PORT": udp_port}),
                                "/": (200, {"FULL_PATH": "/"})})
        self.mgr = VRChatOSCManager(log_dir=None, clock=Clock())
        self.connected = threading.Event()
        self.mgr.on_connected = lambda _ports: self.connected.set()

    def tearDown(self):
        self.mgr.stop()
        self.fake.close()
        self.vrchat_udp.close()

    def receive(self):
        data, sender = self.vrchat_udp.recvfrom(4096)
        msg = OscMessage(data)
        return msg.address, msg.params, sender[1]

    def test_connect_ping_send_and_receive(self):
        self.assertTrue(self.mgr._ensure_sockets())      # zeroconf is off: no advertising
        self.mgr._on_vrchat_found("VRChat-Client-AAAAAA._oscjson._tcp.local.", self.fake.port)
        self.assertTrue(self.connected.is_set())
        self.assertTrue(self.mgr.is_connected)

        # The handshake ping comes from the LISTENER's port, so VRChat learns it.
        address, _params, from_port = self.receive()
        self.assertEqual(address, "/HeightShift/ping")
        self.assertEqual(from_port, self.mgr.local_listen_port)

        self.assertTrue(self.mgr.send_height(150.0))
        address, params, _ = self.receive()
        self.assertEqual((address, params), (VRCHAT_OSC_PATH, [1.5]))

        got = threading.Event()
        heights = []

        def on_height(m, t):
            heights.append((m, t))
            got.set()

        self.mgr.on_height_received = on_height
        sender = SimpleUDPClient("127.0.0.1", self.mgr.local_listen_port)
        sender.send_message(VRCHAT_OSC_PATH, 1.25)
        sender.close()
        self.assertTrue(got.wait(2.0))
        self.assertEqual(heights[0][0], 1.25)

    def _track(self):
        self.assertTrue(self.mgr._ensure_sockets())
        events = []
        self.mgr.on_disconnected = lambda: events.append("disconnected")
        self.mgr.on_connected = lambda ports: events.append(("connected",
                                                             ports["http_oscquery_port"]))
        return events

    def test_a_restarted_vrchat_replaces_the_dead_one(self):
        events = self._track()
        old = FakeVRChat(self.fake.routes)
        self.mgr._on_vrchat_found("VRChat-Client-AAAAAA._oscjson._tcp.local.", old.port)
        self.mgr._on_vrchat_found("VRChat-Client-AAAAAA._oscjson._tcp.local.", old.port)
        old.close()                                        # VRChat crashed …
        self.mgr._on_vrchat_found("VRChat-Client-BBBBBB._oscjson._tcp.local.", self.fake.port)
        # The repeated announcement changed nothing; the restarted VRChat
        # replaced the dead one, with a disconnect in between (the controller
        # then forgets the old height).
        self.assertEqual(events, [("connected", old.port), "disconnected",
                                  ("connected", self.fake.port)])

    def test_a_leftover_dead_record_is_ignored(self):
        # What OscGoesPurrr's log shows: a dead VRChat-Client-305E19 next to
        # the live game. It must not cost the working connection anything.
        events = self._track()
        self.mgr._on_vrchat_found("VRChat-Client-AAAAAA._oscjson._tcp.local.", self.fake.port)
        dead = FakeVRChat({})
        dead_port = dead.port
        dead.close()
        self.mgr._on_vrchat_found("VRChat-Client-DEAD00._oscjson._tcp.local.", dead_port)
        self.mgr._handle_disconnect("removed",
                                    only_name="VRChat-Client-DEAD00._oscjson._tcp.local.")
        self.assertEqual(events, [("connected", self.fake.port)])
        self.assertTrue(self.mgr.is_connected)
        self.assertEqual(self.mgr.http_port, self.fake.port)

    def test_a_second_live_vrchat_does_not_take_over(self):
        events = self._track()
        self.mgr._on_vrchat_found("VRChat-Client-AAAAAA._oscjson._tcp.local.", self.fake.port)
        other = FakeVRChat(self.fake.routes)
        try:
            self.mgr._on_vrchat_found("VRChat-Client-BBBBBB._oscjson._tcp.local.", other.port)
        finally:
            other.close()
        self.assertEqual(events, [("connected", self.fake.port)])

    def test_a_dead_record_while_disconnected_does_not_block_the_live_one(self):
        events = self._track()
        dead = FakeVRChat({})
        dead_port = dead.port
        dead.close()
        self.mgr._on_vrchat_found("VRChat-Client-DEAD00._oscjson._tcp.local.", dead_port)
        self.assertFalse(self.mgr.is_connected)
        self.assertIsNone(self.mgr.http_port)              # the dead port is never kept
        self.mgr._on_vrchat_found("VRChat-Client-AAAAAA._oscjson._tcp.local.", self.fake.port)
        self.assertEqual(events, [("connected", self.fake.port)])


# ----------------------------------------------------------------------
# Which events end a connection
# ----------------------------------------------------------------------

class TestDisconnect(unittest.TestCase):
    def setUp(self):
        self.mgr = connected_manager(5000, name="VRChat-Client-NEW._oscjson._tcp.local.")
        self.count = 0

        def on_disconnected():
            self.count += 1

        self.mgr.on_disconnected = on_disconnected

    def test_removal_of_an_older_record_keeps_the_connection(self):
        self.mgr._handle_disconnect("removed",
                                    only_name="VRChat-Client-OLD._oscjson._tcp.local.")
        self.assertTrue(self.mgr.is_connected)
        self.assertEqual(self.count, 0)

    def test_health_miss_on_an_older_port_keeps_the_connection(self):
        self.mgr._handle_disconnect("no answer", only_port=4000)
        self.assertTrue(self.mgr.is_connected)

    def test_removal_of_our_vrchat_disconnects_once(self):
        name = "VRChat-Client-NEW._oscjson._tcp.local."
        self.mgr._handle_disconnect("removed", only_name=name)
        self.mgr._handle_disconnect("removed", only_name=name)
        self.mgr._handle_disconnect("no answer")
        self.assertFalse(self.mgr.is_connected)
        self.assertEqual(self.count, 1)


class TestNames(unittest.TestCase):
    def test_service_name_shape(self):
        name = make_service_name()
        self.assertRegex(name, r"^HeightShift-[A-Z0-9]{6}$")

    def test_vrchat_is_recognised(self):
        self.assertTrue(is_vrchat_service("VRChat-Client-ABC123._oscjson._tcp.local."))
        self.assertFalse(is_vrchat_service("HeightShift-ABC123._oscjson._tcp.local."))
        self.assertFalse(is_vrchat_service("VRCFT-ABC123._oscjson._tcp.local."))
        self.assertFalse(is_vrchat_service("VRChatTool-ABC123._oscjson._tcp.local."))


if __name__ == "__main__":
    unittest.main()
