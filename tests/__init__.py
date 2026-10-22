"""Test suite for bytecode2code.

Importing the package puts the repository root on ``sys.path`` so the suite
works both as ``python -m tests.run`` and as ``python tests/run.py``.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
