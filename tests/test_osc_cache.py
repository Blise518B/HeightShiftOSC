import unittest

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

try:
    from constants import VRCHAT_OSC_PATH
    from osc_manager import VRChatOSCManager
    _HAVE_OSC = True
except Exception:  # pragma: no cover - only when optional deps are absent
    _HAVE_OSC = False


@unittest.skipUnless(_HAVE_OSC, "osc_manager dependencies not installed")
class TestIncomingOscCache(unittest.TestCase):
    def _make_manager(self):
        mgr = VRChatOSCManager(local_listen_port=0)
        # Don't write to the real diagnostics log from a unit test.
        mgr._log_file_path = None
        return mgr

    def test_eyeheight_packet_is_cached(self):
        mgr = self._make_manager()
        mgr._handle_incoming_osc(VRCHAT_OSC_PATH, 1.75)
        self.assertEqual(mgr._param_cache.get(VRCHAT_OSC_PATH), 1.75)

    def test_other_params_are_not_cached(self):
        mgr = self._make_manager()
        mgr._handle_incoming_osc("/avatar/parameters/SomeBool", True)
        mgr._handle_incoming_osc("/avatar/parameters/Float", 0.5)
        # The cache stays bounded — only the eye-height key is ever stored.
        self.assertEqual(list(mgr._param_cache.keys()), [])

    def test_eyeheight_invokes_height_callback(self):
        mgr = self._make_manager()
        received = []
        mgr.on_height_received = lambda m: received.append(m)
        mgr._handle_incoming_osc(VRCHAT_OSC_PATH, 1.6)
        self.assertEqual(received, [1.6])


if __name__ == "__main__":
    unittest.main()
