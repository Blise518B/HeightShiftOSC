"""Hotkeys: stored keys, their names, and reading them with a fake keyboard."""

import unittest

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

from hotkeys import (
    DEFAULT_GROW,
    DEFAULT_SHRINK,
    MOD_ALT,
    MOD_CTRL,
    MOD_SHIFT,
    Hotkey,
    KeyReader,
    key_name,
)

VK_G, VK_CTRL, VK_SHIFT, VK_ALT = 0x47, 0x11, 0x10, 0x12


class TestHotkeyConfig(unittest.TestCase):
    def test_round_trip(self):
        hk = Hotkey(VK_G, MOD_CTRL | MOD_SHIFT)
        self.assertEqual(Hotkey.from_config(hk.to_config()), hk)

    def test_defaults_are_the_numpad_keys(self):
        self.assertEqual(Hotkey.from_config({"vk": 0x6B, "mods": 0}), DEFAULT_GROW)
        self.assertEqual(Hotkey.from_config({"vk": 0x6D}), DEFAULT_SHRINK)

    def test_rejects_what_isnt_a_hotkey(self):
        for value in ("Num +", None, [], {"vk": True}, {"vk": "71"}, {"vk": 0}, {"vk": 300},
                      {"vk": VK_SHIFT}, {"vk": VK_G, "mods": 8}, {"vk": VK_G, "mods": -1}):
            self.assertIsNone(Hotkey.from_config(value), value)


class TestKeyNames(unittest.TestCase):
    def test_names(self):
        self.assertEqual(key_name(DEFAULT_GROW), "Num +")
        self.assertEqual(key_name(DEFAULT_SHRINK), "Num −")
        self.assertEqual(key_name(Hotkey(VK_G, MOD_CTRL)), "Ctrl + G")
        self.assertEqual(key_name(Hotkey(0x78)), "F9")
        self.assertEqual(key_name(Hotkey(0x65)), "Num 5")
        self.assertEqual(key_name(Hotkey(0x31, MOD_CTRL | MOD_SHIFT | MOD_ALT)),
                         "Ctrl + Shift + Alt + 1")


class TestKeyReader(unittest.TestCase):
    def make(self, front="VRChat.exe"):
        self.down = set()
        return KeyReader(key_down=lambda vk: vk in self.down, foreground_exe=lambda: front)

    def test_held_needs_exactly_its_modifiers(self):
        keys = self.make()
        self.down = {VK_G}
        self.assertTrue(keys.is_held(Hotkey(VK_G)))
        self.assertFalse(keys.is_held(Hotkey(VK_G, MOD_CTRL)))
        self.down = {VK_G, VK_CTRL}
        self.assertTrue(keys.is_held(Hotkey(VK_G, MOD_CTRL)))
        self.assertFalse(keys.is_held(Hotkey(VK_G)))       # G alone doesn't fire for Ctrl + G
        self.down = {VK_G, VK_CTRL, VK_ALT}
        self.assertFalse(keys.is_held(Hotkey(VK_G, MOD_CTRL)))
        self.down = set()
        self.assertFalse(keys.is_held(Hotkey(VK_G)))

    def test_vrchat_in_front(self):
        self.assertTrue(self.make("VRChat.exe").vrchat_in_front())
        self.assertFalse(self.make("Discord.exe").vrchat_in_front())
        self.assertFalse(self.make("").vrchat_in_front())


if __name__ == "__main__":
    unittest.main()
