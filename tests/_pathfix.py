"""Put the project root on sys.path so tests can `import utils` etc.
regardless of how they're launched (unittest discover, pytest, or directly).
Import this first in every test module."""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
