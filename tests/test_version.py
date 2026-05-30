import unittest

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

import version


class TestSanitizeBranch(unittest.TestCase):
    def test_replaces_slashes_with_dashes(self):
        self.assertEqual(version._sanitize_branch("feature/foo"), "feature-foo")

    def test_keeps_allowed_chars(self):
        self.assertEqual(version._sanitize_branch("dev_1.2-x"), "dev_1.2-x")

    def test_collapses_runs_and_strips_edges(self):
        self.assertEqual(version._sanitize_branch("a//b"), "a-b")
        self.assertEqual(version._sanitize_branch("/leading/"), "leading")

    def test_version_resolves_to_nonempty_string(self):
        self.assertIsInstance(version.__version__, str)
        self.assertTrue(version.__version__)


if __name__ == "__main__":
    unittest.main()
