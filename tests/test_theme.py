"""The window under its real stylesheet. The other tests run unstyled, so
they never saw HeightShift 2.0.20's empty number fields: under Qt 6.12 a
styled spin box with NoButtons got a 1 px text field — no number, nothing
to type. Here every number field must show its number and take typing.
Runs Qt offscreen."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractSpinBox, QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from tests import test_controller as _tc  # noqa: E402  (its fakes and fixture, not its tests)
from ui import theme  # noqa: E402


class StyledFieldsTest(_tc.ControllerTest):
    def setUp(self):
        super().setUp()
        theme.apply_theme(_app, mode_name="neon", scale=1.0)

    def tearDown(self):
        _app.setStyleSheet("")                  # the other tests run unstyled
        super().tearDown()

    def test_every_number_field_shows_its_number(self):
        self.make()
        self.window.set_settings_open(True)
        self.window.resize(1100, 790)
        self.window.show()
        QApplication.processEvents()
        spins = [s for s in self.window.findChildren(QAbstractSpinBox) if s.isVisible()]
        self.assertGreaterEqual(len(spins), 5)
        for s in spins:
            with self.subTest(s.text()):
                self.assertGreater(s.lineEdit().width(), s.width() // 2)

    def test_the_duration_takes_typing(self):
        self.make()
        self.window.show()
        QApplication.processEvents()
        spin = self.window.duration_spin
        spin.setFocus()
        spin.selectAll()
        QTest.keyClicks(spin, "45")
        QTest.keyClick(spin, Qt.Key_Return)
        self.assertEqual(spin.value(), 45)


# the inherited ControllerTest tests run in test_controller.py already
for _name in [n for n in dir(_tc.ControllerTest) if n.startswith("test_")]:
    setattr(StyledFieldsTest, _name, None)


if __name__ == "__main__":
    unittest.main()
