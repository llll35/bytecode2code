"""Dump exception table + with analysis for 3.11/3.12."""
import os
import sys
import tempfile
import py_compile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from pyvers import decomp311, worker
from pyvers.pycfile import read_header

SRC = "def f(a, b):\n    with a as x, b as y:\n        return x + y\n"

tmp = tempfile.mkdtemp()
p = os.path.join(tmp, "t.py")
pyc = os.path.join(tmp, "t.pyc")
with open(p, "w") as f:
    f.write(SRC)
py_compile.compile(p, cfile=pyc, doraise=True)
code = worker.load_code(pyc, read_header(pyc).payload_offset)


def find(code, name):
    if code.co_name == name:
        return code
    for c in code.co_consts:
        if hasattr(c, "co_code"):
            got = find(c, name)
            if got is not None:
                return got
    return None


target = find(code, "f")
print("exception entries:")
for e in decomp311._exception_entries(target):
    print("  start=%d end=%d target=%d depth=%d lasti=%d" % (
        e.start, e.end, e.target, e.depth, e.lasti))

rw = decomp311.Rewriter(target)
rw.run()
print("with_setups:", rw.with_setups)
print("with_closes:", rw.with_closes)
print("with_swaps:", rw.with_swaps)
print("with_targets:", rw.with_targets)
