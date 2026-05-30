import unittest

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

from utils import is_valid_host, round_height_cm


class TestRoundHeightCm(unittest.TestCase):
    def test_rounds_to_nearest_int(self):
        self.assertEqual(round_height_cm(170.4), 170)
        self.assertEqual(round_height_cm(169.6), 170)
        self.assertEqual(round_height_cm(171.2), 171)

    def test_half_uses_bankers_rounding(self):
        # round() rounds halves to the nearest even integer; documented here
        # so the behaviour is intentional rather than accidental.
        self.assertEqual(round_height_cm(170.5), 170)
        self.assertEqual(round_height_cm(171.5), 172)

    def test_accepts_numeric_string(self):
        self.assertEqual(round_height_cm("170.2"), 170)

    def test_returns_int_type(self):
        self.assertIsInstance(round_height_cm(170.0), int)


class TestIsValidHost(unittest.TestCase):
    def test_valid_ipv4(self):
        self.assertTrue(is_valid_host("127.0.0.1"))
        self.assertTrue(is_valid_host("192.168.1.50"))

    def test_valid_ipv6(self):
        self.assertTrue(is_valid_host("::1"))

    def test_valid_hostnames(self):
        self.assertTrue(is_valid_host("localhost"))
        self.assertTrue(is_valid_host("my-pc.local"))

    def test_strips_surrounding_whitespace(self):
        self.assertTrue(is_valid_host("  127.0.0.1  "))

    def test_rejects_empty_or_blank(self):
        self.assertFalse(is_valid_host(""))
        self.assertFalse(is_valid_host("   "))

    def test_rejects_garbage(self):
        self.assertFalse(is_valid_host("a b.c"))
        self.assertFalse(is_valid_host("http://x"))
        self.assertFalse(is_valid_host("1.2.3:9000"))

    def test_rejects_non_string(self):
        self.assertFalse(is_valid_host(None))
        self.assertFalse(is_valid_host(123))


if __name__ == "__main__":
    unittest.main()
