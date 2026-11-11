"""The window that offers a newer release (VRCParameterRelay's UpdateDialog,
as a pure view: it shows, the controller downloads and installs).

The one-file Windows exe installs in place: Install now -> the controller
downloads, checks size + SHA-256, hands the swap to a detached helper and
closes the app; the helper replaces the exe and starts the new one (see
updater.py). A build that can't replace itself (run from source) gets the
release page instead.

It pops up on its own, so Enter means Later: Install now reacts only to a
deliberate click (no focus, no auto-default), and the window can't be closed
while a download runs.
"""

from __future__ import annotations

import html

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QPushButton, QVBoxLayout

from .widgets import hbox, label


class UpdateDialog(QDialog):
    install_clicked = Signal()       # download, check and install it
    skip_changed = Signal(str)       # "don't remind me about <tag>": the tag, on close

    def __init__(self, parent, app_name: str, current: str, info: dict,
                 can_install: bool) -> None:
        super().__init__(parent)
        self.info = info
        self.tag = str(info.get("tag") or "")
        self.can_install = can_install
        self._busy = False
        self.setObjectName("UpdateDialog")
        self.setWindowTitle("Update available")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 14)
        lay.setSpacing(12)

        tag = html.escape(self.tag)
        url = html.escape(str(info.get("url") or ""))
        if can_install:
            how = ("<b>Install now</b> downloads it, checks it and restarts the app — your "
                   "heights and settings stay as they are.")
        else:
            how = ("This copy runs from source, so it can't replace itself: get the new "
                   "version from the release page.")
        msg = QLabel(f"<b>{html.escape(app_name)} {tag} is out.</b><br>You're on v{current}. "
                     f'<a href="{url}">See what\'s new</a>.<br><br>{how}')
        msg.setObjectName("UpdateText")
        msg.setTextFormat(Qt.RichText)
        msg.setWordWrap(True)
        msg.setOpenExternalLinks(True)
        lay.addWidget(msg)

        self.status = label("", "UpdateStatus", wrap=True)
        self.status.setVisible(False)
        lay.addWidget(self.status)

        self.dont_remind = QCheckBox(f"Don't remind me about {self.tag} again")
        lay.addWidget(self.dont_remind)

        # Enter means "Later": a keystroke meant for another app must never
        # install and restart mid-session.
        row = hbox(spacing=8)
        row.addStretch(1)
        self.later_btn = QPushButton("Later")
        self.later_btn.setDefault(True)
        self.later_btn.clicked.connect(self.reject)
        row.addWidget(self.later_btn)
        self.page_btn = QPushButton("Release page" if can_install else "Open release page")
        self.page_btn.setAutoDefault(False)
        self.page_btn.clicked.connect(self._open_page)
        row.addWidget(self.page_btn)
        self.install_btn = None
        if can_install:
            self.install_btn = QPushButton("Install now")
            self.install_btn.setObjectName("Primary")
            self.install_btn.setAutoDefault(False)
            self.install_btn.setFocusPolicy(Qt.NoFocus)   # not by Tab + Space either
            self.install_btn.clicked.connect(self._install)
            row.addWidget(self.install_btn)
        else:
            self.page_btn.setObjectName("Primary")
        lay.addLayout(row)

    # --- closing ------------------------------------------------------------

    def done(self, result: int) -> None:  # noqa: D401  (every close path ends here)
        if self._busy:
            return              # mid-download: it stays until that finishes or fails
        if self.dont_remind.isChecked() and self.tag:
            self.skip_changed.emit(self.tag)
        super().done(result)

    def _open_page(self) -> None:
        QDesktopServices.openUrl(QUrl(str(self.info.get("url") or "")))
        self.accept()

    def _install(self) -> None:
        self.set_busy(True)
        self.status.setText("Downloading…")
        self.status.setVisible(True)
        self.adjustSize()                      # grow for the status line, never squeeze
        self.install_clicked.emit()

    # --- setters (controller -> view) ---------------------------------------

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self.later_btn, self.page_btn, self.install_btn, self.dont_remind):
            if widget is not None:
                widget.setEnabled(not busy)

    def set_progress(self, done: int, total: int) -> None:
        mb = done / (1024 * 1024)
        self.status.setText(f"Downloading… {done * 100 // total}%  ({mb:.0f} MB)"
                            if total else f"Downloading… {mb:.0f} MB")

    def set_installing(self) -> None:
        """Checked: the helper takes over and the app closes."""
        self.status.setText("Checked ✓ — restarting to install…")
        self._busy = False

    def set_failed(self, text: str) -> None:
        self.set_busy(False)
        self.status.setText(text)
        self.status.setVisible(True)
        self.adjustSize()                      # grow for the status line, never squeeze
        if self.install_btn is not None:
            self.install_btn.setText("Try again")
