"""The "What's new" window (OscGoesPurrr's, in HeightShift's look).

Opens once at launch after an update (controller.whats_new_on_launch
decides) and from Settings → Updates → What's new. One release per page,
newest first, with Back / Next when there are several. Each change is a
title and a sentence or two beside one of the VRChat menu's icons; a change
that lives somewhere in the app gets a "Take me there" button, which closes
the window and asks the main window to show it (reveal_requested).

The content is whats_new.py; this module only draws it.
"""

from __future__ import annotations

import html
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QLabel, QPushButton, QSizePolicy, QStackedWidget,
                               QWidget)

from .theme import resource_path, text_scale
from .widgets import hbox, label, vbox

WIDTH_PX = 560            # the window's width at 100 % text; its height follows the text
ICON_PX = 22


class WhatsNewDialog(QDialog):
    reveal_requested = Signal(str)        # "Take me there": a place in the window

    def __init__(self, parent, releases, can_reveal: Callable[[str], bool]) -> None:
        """releases: [(version, [(title, text, target, icon), ...]), ...],
        newest first."""
        super().__init__(parent)
        self.setObjectName("WhatsNew")
        self.setWindowTitle("What's new")
        self.setWindowModality(Qt.WindowModal)
        releases = [(v, items) for v, items in releases if items]
        lay = vbox(margin=20, spacing=14)
        self.setLayout(lay)
        icons = any(item[3] for _v, items in releases for item in items)

        self.pages = QStackedWidget()
        for index, (version, items) in enumerate(releases):
            page = QWidget()
            page_lay = vbox(spacing=14)
            page.setLayout(page_lay)
            head = label(f"What's new in v{html.escape(str(version))}" if index == 0
                         else f"Before that, in v{html.escape(str(version))}", "NewsHead")
            page_lay.addWidget(head)
            for title, text, target, icon in items:
                page_lay.addWidget(self._row(title, text, target, icon if icons else None,
                                             can_reveal))
            page_lay.addStretch(1)
            self.pages.addWidget(page)
        lay.addWidget(self.pages)

        self.back = self.next = self.count = None
        if self.pages.count() > 1:
            lay.addLayout(self._pager())

        lay.addSpacing(4)
        foot = hbox(spacing=12)
        foot.addWidget(label("Find this again in Settings → Updates.", "Hint"), 1)
        self.done_btn = QPushButton("Got it")
        self.done_btn.setObjectName("Primary")
        self.done_btn.setDefault(True)
        self.done_btn.clicked.connect(self.accept)
        foot.addWidget(self.done_btn)
        lay.addLayout(foot)

        # The texts wrap, so the height follows the width: fix the width and
        # give every page the room of the tallest, so the window and its
        # buttons stay put while paging.
        width = round(WIDTH_PX * max(1.0, text_scale()))
        self.ensurePolished()
        m = lay.contentsMargins()
        inner = width - m.left() - m.right()
        self.pages.setFixedHeight(max(
            self.pages.widget(i).layout().totalHeightForWidth(inner)
            for i in range(self.pages.count())))
        lay.activate()
        self.setFixedSize(width, lay.totalHeightForWidth(width))

    def _row(self, title: str, text: str, target: str, icon, can_reveal) -> QWidget:
        row = QWidget()
        row_lay = hbox(spacing=12)
        row.setLayout(row_lay)
        if icon is not None:
            mark = QLabel()
            mark.setFixedSize(ICON_PX, ICON_PX)
            pix = QPixmap(resource_path(f"assets/menu/{icon}.png")) if icon else QPixmap()
            if not pix.isNull():
                dpr = self.devicePixelRatioF() or 1.0
                pix = pix.scaled(round(ICON_PX * dpr), round(ICON_PX * dpr), Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation)
                pix.setDevicePixelRatio(dpr)
                mark.setPixmap(pix)
            row_lay.addWidget(mark, 0, Qt.AlignTop)
        col = vbox(spacing=2)
        col.addWidget(label(str(title), "NewsTitle"))
        body = label(str(text), "NewsText", wrap=True)
        body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        col.addWidget(body)
        row_lay.addLayout(col, 1)
        if target and can_reveal(target):
            go = QPushButton("Take me there")
            go.setObjectName("Small")
            go.setCursor(Qt.PointingHandCursor)
            go.clicked.connect(lambda _c=False, place=target: self._go(place))
            row_lay.addWidget(go, 0, Qt.AlignVCenter)
        return row

    def _go(self, place: str) -> None:
        self.accept()
        self.reveal_requested.emit(place)

    def _pager(self):
        """Back / "2 of 3" / Next. A button with nowhere to go hides but keeps
        its room, so the other one stays under the pointer."""
        nav = hbox(spacing=12)
        self.back = QPushButton("← Back")
        self.next = QPushButton("Next →")
        self.count = label("", "Hint")
        self.count.setAlignment(Qt.AlignCenter)
        for button in (self.back, self.next):
            button.setCursor(Qt.PointingHandCursor)
            button.setAutoDefault(False)
            policy = button.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            button.setSizePolicy(policy)
        nav.addWidget(self.back)
        nav.addWidget(self.count, 1)
        nav.addWidget(self.next)
        self.back.clicked.connect(lambda: self.turn(-1))
        self.next.clicked.connect(lambda: self.turn(1))
        self.turn(0)
        return nav

    def turn(self, step: int) -> None:
        at = max(0, min(self.pages.count() - 1, self.pages.currentIndex() + step))
        self.pages.setCurrentIndex(at)
        if self.back is not None:
            self.back.setVisible(at > 0)
            self.next.setVisible(at < self.pages.count() - 1)
            self.count.setText(f"{at + 1} of {self.pages.count()}")
