"""What's new: the rule for when it shows (once after an update, never on a
first install), its content's targets and icons, the window's pages and
"Take me there", and the update window waiting for it. Runs Qt offscreen."""

import json
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import whats_new  # noqa: E402
from tests import test_controller as _tc  # noqa: E402  (its fakes and fixture, not its tests)
from ui.theme import resource_path  # noqa: E402
from ui.window import PLACES  # noqa: E402

NEWEST = whats_new.RELEASES[0].version


class RuleTest(unittest.TestCase):
    def test_unseen_after_an_update(self):
        all_versions = [r.version for r in whats_new.RELEASES]
        self.assertEqual([r.version for r in whats_new.unseen_releases("", NEWEST)], all_versions)
        self.assertEqual([r.version for r in whats_new.unseen_releases("2.0.20", NEWEST)],
                         all_versions[:-1])
        self.assertEqual(whats_new.unseen_releases(NEWEST, NEWEST), [])

    def test_never_a_version_after_this_build(self):
        self.assertEqual([r.version for r in whats_new.releases_for("2.0.23")],
                         ["2.0.23", "2.0.20"])
        # a source run's branch suffix counts as its number
        self.assertEqual(whats_new.releases_for(NEWEST + "-feature(0)")[0].version, NEWEST)

    def test_newest_first_and_every_place_and_icon_exist(self):
        versions = [whats_new._version(r.version) for r in whats_new.RELEASES]
        self.assertEqual(versions, sorted(versions, reverse=True))
        for release in whats_new.RELEASES:
            for item in release.items:
                with self.subTest(item.title):
                    if item.target:
                        self.assertIn(item.target, PLACES)
                    if item.icon:
                        self.assertTrue(os.path.isfile(resource_path(f"assets/menu/{item.icon}.png")))


class LaunchTest(_tc.ControllerTest):
    def dialog(self):
        return getattr(self.window, "whats_new_dialog", None)

    def test_a_first_install_starts_up_to_date(self):
        self.make()                                         # no config file before
        self.assertFalse(self.c.whats_new_on_launch(NEWEST))
        self.assertIsNone(self.dialog())
        self.assertEqual(self.c.config.get_str(whats_new.SEEN_KEY), NEWEST)

    def test_an_update_shows_each_unseen_release_once(self):
        with open(self.cfg_path, "w", encoding="utf-8") as f:     # an install from before
            json.dump({"profiles": {}}, f)
        self.make()
        self.assertTrue(self.c.whats_new_on_launch(NEWEST))
        dlg = self.dialog()
        self.assertTrue(dlg.isVisible())
        self.assertEqual(dlg.pages.count(), len(whats_new.RELEASES))
        self.assertEqual(dlg.count.text(), f"1 of {len(whats_new.RELEASES)}")
        self.assertFalse(dlg.back.isVisible())
        dlg.next.click()
        self.assertEqual(dlg.count.text(), f"2 of {len(whats_new.RELEASES)}")
        self.assertTrue(dlg.back.isVisible())
        dlg.done_btn.click()
        self.assertFalse(dlg.isVisible())
        self.assertEqual(self.c.config.get_str(whats_new.SEEN_KEY), NEWEST)
        self.assertFalse(self.c.whats_new_on_launch(NEWEST))         # not twice

    def test_settings_button_shows_every_release(self):
        self.make()
        self.c.whats_new_on_launch(NEWEST)                  # first install: quiet
        self.window.whats_new_btn.click()
        self.assertEqual(self.dialog().pages.count(), len(whats_new.RELEASES))

    def test_take_me_there_opens_and_lights_the_place(self):
        import ui.window as window_module
        beats, window_module.SPOT_BEATS = window_module.SPOT_BEATS, ((0, True),)
        self.addCleanup(setattr, window_module, "SPOT_BEATS", beats)  # lit, and it stays
        self.make(settings_open=False)
        self.window.show()
        self.window.show_whats_new([("9.9", [("T", "text", "updates", "")])])
        dlg = self.dialog()
        go = [b for b in dlg.findChildren(type(self.window.whats_new_btn))
              if b.text() == "Take me there"]
        self.assertEqual(len(go), 1)
        go[0].click()
        self.assertFalse(dlg.isVisible())
        self.assertTrue(self.window.settings_btn.isChecked())        # Settings opened
        QTest.qWait(80)
        self.assertEqual(self.window.updates_group.property("spot"), "true")
        for place in PLACES:
            self.assertTrue(self.window.can_reveal(place), place)
        self.assertFalse(self.window.can_reveal("nowhere"))

    def test_the_update_window_waits_for_whats_new(self):
        self.make()
        self.window.show_whats_new(whats_new.as_plain(whats_new.RELEASES))
        info = {"available": True, "tag": "v9.9.9", "url": "https://x", "asset": None}
        self.assertIsNone(self.window.show_update_dialog(info, False))
        self.assertEqual(self.window._update_waiting, (info, False))


# the inherited ControllerTest tests run in test_controller.py already
for _name in [n for n in dir(_tc.ControllerTest) if n.startswith("test_")]:
    setattr(LaunchTest, _name, None)


if __name__ == "__main__":
    unittest.main()
