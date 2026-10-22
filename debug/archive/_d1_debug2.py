"""Debug D1: 3.12 module-level try/except swallowing code after block."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pyvers

src = """\
try:
    x = 1
except Exception:
    x = 2

class Foo:
    pass
"""

for ver in ("3.9", "3.11", "3.12"):
    print(f"=== {ver} decompile ===")
    path = os.path.join(tempfile.gettempdir(), f"d1debug_{ver}.pyc")
    pyvers.compile_source(src, path, version=ver)
    out = pyvers.decompile(path)
    print(out["source"])
    print()
