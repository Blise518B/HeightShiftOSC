import json
import os
import shutil
import tempfile
import unittest

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

from config_manager import ConfigManager


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="hso-test-")
        # Deliberately nested so we also exercise the makedirs in _atomic_write.
        self.cfg_path = os.path.join(self.tmpdir, "sub", "config.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_defaults_when_file_missing(self):
        cm = ConfigManager(self.cfg_path)
        self.assertEqual(cm.config["startup_mode"], "query")
        self.assertIn("profiles", cm.config)

    def test_save_round_trip(self):
        cm = ConfigManager(self.cfg_path)
        cm.save_config({"osc_ip": "10.0.0.5", "profiles": {"profile1": 180}})

        with open(self.cfg_path, encoding="utf-8") as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk["osc_ip"], "10.0.0.5")

        # save_config must refresh the in-memory copy (no stale drift).
        self.assertEqual(cm.config["osc_ip"], "10.0.0.5")

        # A fresh manager reads the same data back.
        cm2 = ConfigManager(self.cfg_path)
        self.assertEqual(cm2.config["profiles"]["profile1"], 180)

    def test_update_config_merges_and_persists(self):
        cm = ConfigManager(self.cfg_path)
        cm.save_config({"osc_ip": "1.1.1.1"})
        cm.update_config({"hide_console": False})

        cm2 = ConfigManager(self.cfg_path)
        self.assertEqual(cm2.config["osc_ip"], "1.1.1.1")
        self.assertEqual(cm2.config["hide_console"], False)

    def test_atomic_write_leaves_no_temp_files(self):
        cm = ConfigManager(self.cfg_path)
        cm.save_config({"osc_ip": "2.2.2.2"})
        leftovers = [
            n for n in os.listdir(os.path.dirname(self.cfg_path))
            if n.endswith(".tmp")
        ]
        self.assertEqual(leftovers, [])

    def test_corrupt_file_falls_back_to_defaults(self):
        os.makedirs(os.path.dirname(self.cfg_path), exist_ok=True)
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write("{ not valid json ")
        cm = ConfigManager(self.cfg_path)
        self.assertEqual(cm.config["startup_mode"], "query")


if __name__ == "__main__":
    unittest.main()
