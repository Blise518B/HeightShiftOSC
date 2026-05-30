import unittest

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

try:
    from osc_manager import VRChatOSCManager
    _HAVE_OSC = True
except Exception:  # pragma: no cover - only when optional deps are absent
    _HAVE_OSC = False


@unittest.skipUnless(_HAVE_OSC, "osc_manager dependencies not installed")
class TestFlattenOscQueryNode(unittest.TestCase):
    def test_flattens_nested_tree(self):
        tree = {
            "NAME": "root",
            "CONTENTS": {
                "avatar": {
                    "FULL_PATH": "/avatar",
                    "CONTENTS": {
                        "eyeheight": {"FULL_PATH": "/avatar/eyeheight", "VALUE": [1.7]},
                        "change": {"FULL_PATH": "/avatar/change", "VALUE": ["abc"]},
                        "nested": {
                            "FULL_PATH": "/avatar/nested",
                            "CONTENTS": {
                                "x": {"FULL_PATH": "/avatar/nested/x", "VALUE": [5]},
                            },
                        },
                    },
                }
            },
        }
        flat = VRChatOSCManager._flatten_oscquery_node(tree)
        self.assertEqual(flat["/avatar/eyeheight"], [1.7])
        self.assertEqual(flat["/avatar/change"], ["abc"])
        self.assertEqual(flat["/avatar/nested/x"], [5])
        # A node with CONTENTS but no VALUE is not itself emitted.
        self.assertNotIn("/avatar", flat)

    def test_handles_non_dict_input(self):
        self.assertEqual(VRChatOSCManager._flatten_oscquery_node(None), {})
        self.assertEqual(VRChatOSCManager._flatten_oscquery_node([]), {})

    def test_empty_tree(self):
        self.assertEqual(VRChatOSCManager._flatten_oscquery_node({}), {})


if __name__ == "__main__":
    unittest.main()
