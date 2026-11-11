"""The slow-transition graph: height over time, with a playhead."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from height_logic import CURVE_LINEAR, format_height, interpolate

from .theme import colors, text_scale

GRAPH_HEIGHT = 112


class TransitionGraph(QWidget):
    """Height over time for the planned / running transition. Draws exactly
    what will be sent (same `interpolate` the controller uses), with a
    playhead while it plays."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(GRAPH_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._start: Optional[float] = None
        self._end: float = 200.0
        self._duration_text = ""
        self._curve = CURVE_LINEAR
        self._progress: Optional[float] = None

    def set_plan(self, start_cm: Optional[float], end_cm: float, duration_text: str,
                 curve: str) -> None:
        self._start, self._end = start_cm, end_cm
        self._duration_text, self._curve = duration_text, curve
        self.update()

    def set_progress(self, fraction: Optional[float]) -> None:
        self._progress = fraction
        self.update()

    def sizeHint(self):  # noqa: N802
        size = super().sizeHint()
        size.setHeight(int(GRAPH_HEIGHT * text_scale()))
        return size

    def paintEvent(self, _event):  # noqa: N802
        c = colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        font = p.font()
        font.setPixelSize(max(9, round(11 * text_scale())))
        p.setFont(font)
        fm = p.fontMetrics()

        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        # the Timed transition card's yellow (theme.colors "timed"), like Go timed
        accent, faded, rim = c["timed"], c["timed_mid"], c["timed_mid"]
        p.setPen(QPen(QColor(rim), 1))
        p.setBrush(QColor(c["well"]))
        p.drawRoundedRect(outer, 8, 8)

        if self._start is None:
            p.setPen(QColor(c["dim"]))
            p.drawText(outer, Qt.AlignCenter,
                       "Waiting for VRChat's current height —\n"
                       "the transition starts from it.")
            return

        pad_x, pad_top, pad_bottom = 14.0, 10.0 + fm.height(), 10.0 + fm.height()
        plot = outer.adjusted(pad_x, pad_top, -pad_x, -pad_bottom)
        lo, hi = min(self._start, self._end), max(self._start, self._end)
        if hi - lo < 1e-6:
            lo, hi = lo - 1.0, hi + 1.0

        def pt(f: float) -> QPointF:
            v = interpolate(self._start, self._end, f, self._curve)
            y = plot.bottom() - (v - lo) / (hi - lo) * plot.height()
            return QPointF(plot.left() + f * plot.width(), y)

        samples = 120
        done = self._progress if self._progress is not None else 0.0
        full = QPainterPath(pt(0.0))
        for i in range(1, samples + 1):
            full.lineTo(pt(i / samples))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(faded if done > 0 else accent), 2.2,
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(full)

        if done > 0:
            n = max(2, int(samples * done))
            path = QPainterPath(pt(0.0))
            for i in range(1, n + 1):
                path.lineTo(pt(done * i / n))
            p.setPen(QPen(QColor(accent), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)

        # Labels in the text rows above and below the plot, each in the corner
        # next to its own point, so none ever crosses the line:
        #   rising:  start bottom-left, end top-right, duration bottom-right
        #   falling: start top-left, end bottom-right, duration top-right
        rising = self._end >= self._start
        top_row = QRectF(plot.left(), outer.top() + 4, plot.width(), fm.height())
        bottom_row = QRectF(plot.left(), outer.bottom() - 4 - fm.height(), plot.width(),
                            fm.height())
        left, right = Qt.AlignLeft | Qt.AlignVCenter, Qt.AlignRight | Qt.AlignVCenter
        p.setPen(QColor(c["muted"]))
        p.drawText(bottom_row if rising else top_row, left, format_height(self._start))
        p.setPen(QColor(accent))
        p.drawText(top_row if rising else bottom_row, right, format_height(self._end))
        p.setPen(QColor(c["dim"]))
        p.drawText(bottom_row if rising else top_row, right, self._duration_text)

        if self._progress is not None:
            head = pt(done)
            accent = QColor(accent)
            line = QColor(accent)
            line.setAlpha(110)
            p.setPen(QPen(line, 1))
            p.drawLine(QPointF(head.x(), plot.top()), QPointF(head.x(), plot.bottom()))
            glow = QColor(accent)
            glow.setAlpha(70)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(head, 7, 7)
            p.setBrush(accent)
            p.drawEllipse(head, 4, 4)


