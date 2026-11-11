"""
main.py — HeightShift entry point.

Where things live:
    controller.py      what gets sent to VRChat and when (the two rules: one write path, one read path)
    height_logic.py    the rules themselves, without Qt or network (limits, trusting reports,
                       the height to keep across avatar changes, the transition clock)
    osc/               the connection to VRChat (OSC + OSCQuery, mDNS, the 518 router fallback)
    ui/                the PySide6 window in the 518 design system
    config_manager.py  the settings file
"""

from __future__ import annotations

import atexit
import logging
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

import single_instance
from config_manager import ConfigManager, get_app_config_dir
from console_window import ConsoleWindow
from constants import (
    APP_NAME,
    CONFIG_FILE_NAME,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    LOG_DATE_FORMAT,
    LOG_FORMAT,
)
from controller import HeightShiftController
from ui import theme, wheel_guard
from ui.window import HeightShiftWindow
from version import TITLE_TAG, __version__

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)


def main() -> int:
    console = ConsoleWindow()
    atexit.register(console.restore)

    config_dir = get_app_config_dir()
    guard = single_instance.acquire(config_dir)
    if guard is None:
        logger.info(f"{APP_NAME} is already running — brought its window to the front.")
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    wheel_guard.install(app)          # before the window: its Ctrl+wheel filter runs first
    theme.register_fonts()

    config = ConfigManager(os.path.join(config_dir, CONFIG_FILE_NAME))
    theme.apply_theme(
        app,
        mode_name=config.get_choice("ui_mode", "neon", ("neon", "midnight", "broker")),
        scale=config.get_number("text_scale", 1.0, theme.TEXT_SCALES[0], theme.TEXT_SCALES[-1]))

    icon_path = theme.resource_path("OSC_Scale.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = HeightShiftWindow(TITLE_TAG, __version__.split("-")[0])
    controller = HeightShiftController(window, config, console)
    guard.on_activate = controller.activate_requested.emit
    window.restore_window(config.get_str("window_geometry_qt"),
                          config.get_str("window_geometry"),
                          DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    window.show()
    controller.start()
    controller.check_for_updates(__version__)      # GitHub, on a worker thread
    # after an update: what changed, once (its update offer waits for it)
    QTimer.singleShot(1200, lambda: controller.whats_new_on_launch(__version__))
    try:
        return app.exec()
    finally:
        guard.release()


if __name__ == "__main__":
    sys.exit(main())
