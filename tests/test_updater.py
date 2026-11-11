"""The self-updater (updater.py, VRCParameterRelay's) and the update window's
flows, hermetic: no network, nothing is replaced. The version compare, which
release asset is ours, the release check, the verified download, the swap's
guards — and in the app: the start's check opens the window unless that
version was skipped, Enter means Later, Install downloads -> swaps -> closes,
and a failed download changes nothing. Runs Qt offscreen."""

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import updater  # noqa: E402
from tests import test_controller as _tc  # noqa: E402  (its fakes and fixture, not its tests)


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, length=None, status=200, explode_after=None):
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Length": str(len(body) if length is None else length)}
        self._explode_after = explode_after

    def read(self, n=-1):
        if self._explode_after is not None and self.tell() >= self._explode_after:
            raise ConnectionResetError("connection dropped")
        return super().read(n)


def serving(responses):
    """Patch updater._open to answer from a {url: response or exception} table."""
    def fake_open(url, timeout):
        resp = responses.get(url)
        if isinstance(resp, Exception):
            raise resp
        if resp is None:
            raise OSError(f"no fake for {url}")
        return resp
    return mock.patch.object(updater, "_open", fake_open)


EXE = b"MZ" + b"\x00" * 5000
EXE_SHA = hashlib.sha256(EXE).hexdigest()
EXE_URL = "https://github.com/Blise518B/HeightShiftOSC/releases/download/v2.0.30/HeightShift.exe"


def release(tag="v2.0.30", assets=None):
    return {"tag_name": tag, "html_url": "https://github.com/Blise518B/HeightShiftOSC/releases/tag/"
            + tag, "assets": assets if assets is not None else [
                {"name": "HeightShift-VRCFury.unitypackage", "size": 10,
                 "browser_download_url": "https://example.invalid/pkg"},
                {"name": "HeightShift.exe", "size": len(EXE), "digest": f"sha256:{EXE_SHA}",
                 "browser_download_url": EXE_URL}]}


def asset(**over):
    a = {"name": "HeightShift.exe", "url": EXE_URL, "size": len(EXE), "sha256": EXE_SHA}
    a.update(over)
    return a


class VersionTest(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(updater.parse_version("v2.0.31"), (2, 0, 31))
        self.assertEqual(updater.parse_version("2.0.31-feature-x(4)"), (2, 0, 31))
        self.assertIsNone(updater.parse_version("latest"))
        self.assertTrue(updater.is_newer("v2.0.31", "2.0.30"))
        self.assertTrue(updater.is_newer("v2.1", "2.0.99"))
        self.assertFalse(updater.is_newer("v2.0.30", "2.0.30-feature(3)"))
        self.assertFalse(updater.is_newer("junk", "2.0.1"))

    def test_only_our_https_exe_is_the_asset(self):
        picked = updater.pick_exe_asset(release()["assets"])
        self.assertEqual(picked["name"], "HeightShift.exe")
        self.assertEqual(picked["sha256"], EXE_SHA)
        self.assertIsNone(updater.pick_exe_asset([{"name": "Other.exe", "browser_download_url":
                                                   "https://x/Other.exe"}]))
        self.assertIsNone(updater.pick_exe_asset([{"name": "HeightShift.exe",
                                                   "browser_download_url": "http://x/a.exe"}]))
        self.assertIsNone(updater.pick_exe_asset("junk"))
        bad = updater.pick_exe_asset([{"name": "HeightShift.exe", "digest": "sha256:xyz",
                                       "browser_download_url": "https://x/a.exe"}])
        self.assertIsNone(bad["sha256"])                        # a junk digest is no digest

    def test_a_source_run_can_not_replace_itself(self):
        self.assertFalse(updater.is_self_updatable())
        self.assertFalse(updater.apply_update(os.path.join(tempfile.gettempdir(), "nope.exe")))


class CheckTest(unittest.TestCase):
    def test_newer_same_offline_junk(self):
        body = json.dumps(release()).encode()
        with serving({updater.LATEST_API: FakeResponse(body)}):
            info = updater.check_for_update("2.0.12")
        self.assertTrue(info["available"])
        self.assertEqual((info["tag"], info["latest"]), ("v2.0.30", "2.0.30"))
        self.assertEqual(info["asset"]["url"], EXE_URL)
        with serving({updater.LATEST_API: FakeResponse(body)}):
            self.assertFalse(updater.check_for_update("2.0.30")["available"])
        with serving({updater.LATEST_API: OSError("offline")}):
            self.assertIsNone(updater.check_for_update("2.0.12"))
        with serving({updater.LATEST_API: FakeResponse(b"<html>rate limited</html>")}):
            self.assertIsNone(updater.check_for_update("2.0.12"))
        with serving({updater.LATEST_API: FakeResponse(json.dumps(release("nightly")).encode())}):
            self.assertIsNone(updater.check_for_update("2.0.12"))


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.before = set(os.listdir(tempfile.gettempdir()))

    def leftovers(self):
        return [n for n in set(os.listdir(tempfile.gettempdir())) - self.before
                if n.startswith("HeightShift_update_")]

    def test_a_good_download_is_verified_and_kept(self):
        seen = []
        with serving({EXE_URL: FakeResponse(EXE)}):
            path = updater.download_update(asset(), progress=lambda d, t: seen.append((d, t)))
        try:
            self.assertIsNotNone(path)
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), EXE)
            self.assertEqual(seen[-1], (len(EXE), len(EXE)))
        finally:
            os.unlink(path)

    def test_a_bad_download_is_refused_and_removed(self):
        cases = {
            "wrong digest": (asset(sha256="0" * 64), FakeResponse(EXE)),
            "truncated": (asset(), FakeResponse(EXE[:100])),
            "dropped": (asset(), FakeResponse(EXE, explode_after=1000)),
            "empty": (asset(size=0, sha256=None), FakeResponse(b"")),
            "huge": (asset(size=0, sha256=None), FakeResponse(EXE, length=10 ** 10)),
            "not https": (asset(url="http://x/HeightShift.exe"), FakeResponse(EXE)),
        }
        for name, (a, resp) in cases.items():
            with self.subTest(name), serving({a["url"]: resp}):
                self.assertIsNone(updater.download_update(a))
        self.assertEqual(self.leftovers(), [])


class AppUpdateTest(_tc.ControllerTest):
    """The update flows in the app, with the network and the swap stubbed."""

    INFO = {"available": True, "tag": "v2.0.30", "latest": "2.0.30",
            "url": "https://github.com/Blise518B/HeightShiftOSC/releases/tag/v2.0.30",
            "asset": asset(), "assets": []}

    def dialog(self):
        return getattr(self.window, "update_dialog", None)

    def test_the_start_check_opens_the_window_and_lights_the_chip(self):
        self.make()
        self.c._on_update_checked(dict(self.INFO), False)
        self.assertFalse(self.window.update_chip.isHidden())
        self.assertIn("v2.0.30", self.window.update_chip.text())
        self.assertIsNotNone(self.dialog())
        self.assertTrue(self.dialog().isVisible())
        # from source it can't install itself: the release page is the way
        self.assertIsNone(self.dialog().install_btn)
        self.assertEqual(self.dialog().page_btn.objectName(), "Primary")

    def test_a_skipped_version_stays_quiet_at_start_but_not_by_hand(self):
        self.make(skip_update_version="v2.0.30")
        self.c._on_update_checked(dict(self.INFO), False)
        self.assertIsNone(self.dialog())
        self.assertFalse(self.window.update_chip.isHidden())        # the chip still says so
        self.c._on_update_checked(dict(self.INFO), True)
        self.assertIsNotNone(self.dialog())
        self.assertEqual(self.window.update_result.text(), "v2.0.30 is available.")

    def test_dont_remind_me_stores_the_tag_and_hides_the_chip(self):
        self.make()
        self.c._on_update_checked(dict(self.INFO), False)
        self.dialog().dont_remind.setChecked(True)
        self.dialog().later_btn.click()
        self.assertEqual(self.c.config.get_str("skip_update_version"), "v2.0.30")
        self.assertTrue(self.window.update_chip.isHidden())

    def test_by_hand_up_to_date_and_offline(self):
        self.make()
        self.c._on_update_checked(dict(self.INFO, available=False), True)
        self.assertEqual(self.window.update_result.text(), "You're up to date.")
        self.assertIsNone(self.dialog())
        self.c._on_update_checked(None, True)
        self.assertEqual(self.window.update_result.text(),
                         "Couldn't reach GitHub — try again later.")

    def test_enter_means_later_never_install(self):
        self.make()
        with mock.patch.object(updater, "is_self_updatable", return_value=True):
            self.c._on_update_checked(dict(self.INFO), False)
        dlg = self.dialog()
        self.assertIsNotNone(dlg.install_btn)
        self.assertTrue(dlg.later_btn.isDefault())
        self.assertEqual(dlg.install_btn.focusPolicy(), Qt.NoFocus)
        with mock.patch.object(updater, "download_update") as download:
            QTest.keyClick(dlg, Qt.Key_Return)
            download.assert_not_called()
        self.assertFalse(dlg.isVisible())

    def test_install_downloads_swaps_and_closes(self):
        self.make()
        closed = []
        self.window.set_close_handler(lambda: closed.append(True))
        with mock.patch.object(updater, "is_self_updatable", return_value=True):
            self.c._on_update_checked(dict(self.INFO), False)
            dlg = self.dialog()
            with mock.patch.object(updater, "download_update", return_value="C:/t/new.exe"), \
                    mock.patch.object(updater, "apply_update", return_value=True) as apply:
                dlg.install_btn.click()
                self.assertTrue(dlg._busy)
                dlg.reject()                                    # can't close mid-download
                self.assertTrue(dlg.isVisible())
                for _ in range(100):                            # the worker thread answers
                    QTest.qWait(10)
                    if apply.called:
                        break
                apply.assert_called_once_with("C:/t/new.exe")
        self.assertEqual(closed, [True])                        # the app closed for the swap

    def test_a_failed_download_changes_nothing(self):
        self.make()
        with mock.patch.object(updater, "is_self_updatable", return_value=True):
            self.c._on_update_checked(dict(self.INFO), False)
        dlg = self.dialog()
        with mock.patch.object(updater, "apply_update") as apply:
            self.c._on_update_downloaded("")
            apply.assert_not_called()
        self.assertFalse(dlg._busy)
        self.assertEqual(dlg.install_btn.text(), "Try again")
        self.assertIn("nothing was changed", dlg.status.text())


# the inherited ControllerTest tests run in test_controller.py already
for _name in [n for n in dir(_tc.ControllerTest) if n.startswith("test_")]:
    setattr(AppUpdateTest, _name, None)


if __name__ == "__main__":
    unittest.main()
