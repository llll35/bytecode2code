"""Decompile one flow probe with the running version's decompiler."""
import os
import sys
import tempfile
import py_compile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.cases import FLOW_PROBES  # noqa: E402
from tests.test_roundtrip import decompile_sample  # noqa: E402

key = sys.argv[1] if len(sys.argv) > 1 else "try_except_else_finally"
src = FLOW_PROBES[key]
print("--- source ---")
print(src)
with tempfile.TemporaryDirectory() as tmp:
    p = os.path.join(tmp, "p.py")
    c = os.path.join(tmp, "p.pyc")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(src)
    py_compile.compile(p, cfile=c, doraise=True)
    print("--- output (py%d.%d) ---" % sys.version_info[:2])
    print(decompile_sample(c))
