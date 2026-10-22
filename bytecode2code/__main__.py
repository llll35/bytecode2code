"""``python -m bytecode2code`` -- the single-interpreter front end.

Reads bytecode with the interpreter that is running, so it only handles the
version it was written for.  ``python main.py`` at the repository root routes a
file to whichever embedded interpreter matches it instead.
"""

import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())