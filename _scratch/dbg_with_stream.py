"""Dump the translated 3.9-shape stream for a with sample.

    embed_python\\python-3.12\\python.exe -B _scratch\\dbg_with_stream.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from pyvers import decomp311, worker
from pyvers.pycfile import read_header

SRC = "def f(a, b):\n    with a as x, b as y:\n        return x + y\n"

import tempfile, py_compile

tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "t.py")
pyc = os.path.join(tmp, "t.pyc")
with open(path, "w") as f:
    f.write(SRC)
py_compile.compile(path, cfile=pyc, doraise=True)

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
rw = decomp311.Rewriter(target)
out = rw.run()

print("=== RAW ===")
for i, r in enumerate(rw.raw):
    print("%3d %4d %-24s %r" % (i, r.offset, r.opname, r.argval))

print()
print("with_setups:", rw.with_setups)
print("with_closes:", rw.with_closes)
print("with_swaps:", rw.with_swaps)
print("with_exits:", rw.with_exits)
print("try_closes:", rw.try_closes)
print("drops:", sorted(rw._drops))

print()
print("=== TRANSLATED (3.9 shape) ===")
for i, x in enumerate(out):
    print("%3d %4d %-24s %r" % (i, x.offset, x.opname, x.argval))

print()
print("=== OUTPUT ===")
dec = decomp311.Decompiler311()
print(dec.decompile(target))
