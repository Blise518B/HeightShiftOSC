"""Make the size comparison's filled silhouette from the line-art figure.

  assets/figure.png        her lines: OscGoesPurrr's Suits cat girl
                           (src/Images/suits/front.png, same author, MIT),
                           white with the drawing's alpha
  assets/figure_fill.png   written here: everything inside her outline,
                           white with alpha, the same size

The fill is the drawing's inside: every pixel the outside can't reach from
the image border without crossing a line. The lines are thickened by a pixel
first so a hairline gap in the drawing doesn't let the outside
leak in. Committed; re-run only for a new drawing.

Run from the project root:
    venv\\Scripts\\python.exe tools\\make_figure_assets.py
"""

import os
import sys
from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "figure.png")
DST = os.path.join(ROOT, "assets", "figure_fill.png")
LINE_ALPHA = 40          # a pixel at least this opaque is a line
WORK_SCALE = 1.0         # full size: keeps the gaps between arms and body open


def main() -> None:
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    src = QImage(SRC)
    if src.isNull():
        sys.exit(f"can't read {SRC}")
    full_w, full_h = src.width(), src.height()
    small = src.scaled(round(full_w * WORK_SCALE), round(full_h * WORK_SCALE),
                       Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small = small.convertToFormat(QImage.Format_ARGB32)
    w, h = small.width(), small.height()
    raw = bytes(small.constBits())
    stride = small.bytesPerLine()
    line = bytearray(w * h)
    for y in range(h):
        row = y * stride
        for x in range(w):
            if raw[row + x * 4 + 3] >= LINE_ALPHA:
                line[y * w + x] = 1
    # thicken the lines by one pixel so the outside can't slip through a gap
    wall = bytearray(line)
    for y in range(h):
        for x in range(w):
            if line[y * w + x]:
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        yy, xx = y + dy, x + dx
                        if 0 <= yy < h and 0 <= xx < w:
                            wall[yy * w + xx] = 1
    outside = bytearray(w * h)
    queue = deque()
    for x in range(w):
        queue.extend(((x, 0), (x, h - 1)))
    for y in range(h):
        queue.extend(((0, y), (w - 1, y)))
    while queue:
        x, y = queue.popleft()
        i = y * w + x
        if outside[i] or wall[i]:
            continue
        outside[i] = 1
        if x > 0:
            queue.append((x - 1, y))
        if x < w - 1:
            queue.append((x + 1, y))
        if y > 0:
            queue.append((x, y - 1))
        if y < h - 1:
            queue.append((x, y + 1))
    mask = QImage(w, h, QImage.Format_ARGB32)
    mask.fill(QColor(255, 255, 255, 0))
    white = QColor(255, 255, 255, 255).rgba()
    for y in range(h):
        for x in range(w):
            if not outside[y * w + x]:
                mask.setPixel(x, y, white)
    mask = mask.scaled(full_w, full_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    mask.save(DST)
    inside = sum(1 for v in outside if not v)
    print(f"{os.path.basename(DST)}: {full_w} x {full_h}, inside {inside * 100 // (w * h)} %")


if __name__ == "__main__":
    main()
