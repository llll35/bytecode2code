"""Instrument _analyse_with decisions for 3.11."""
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
rw = decomp311.Rewriter(target)
raw = rw.raw
by_offset = {r.offset: n for n, r in enumerate(raw)}
entries = decomp311._exception_entries(target)
handler_targets = {e.target for e in entries}
targets = {120, 72}  # from with_targets for 3.11
print("attr_method_bit:", rw.attr_method_bit)
for e in entries:
    if e.target not in targets or e.end >= e.target:
        print("entry", e.start, e.end, e.target, "SKIP(not body)")
        continue
    if any(e.start <= t < e.end for t in handler_targets if t != e.target):
        print("entry", e.start, e.end, e.target, "SKIP(nested target)")
        continue
    position = by_offset.get(e.end)
    if position is None:
        print("entry", e.start, e.end, e.target, "SKIP(no position)")
        continue
    close = rw._close_starts_exit(position)
    exit_call = rw._find_exit_call(position)
    print("entry", e.start, e.end, e.target,
          "pos", position, raw[position].opname,
          "close_starts_exit", close,
          "find_exit_call", exit_call.offset if exit_call else None)
