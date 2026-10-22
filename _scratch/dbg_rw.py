"""Dump the decomp311 Rewriter output (back-translated 3.9-shape stream).

Run under the 3.11 embedded interpreter:
  embed_python/python-3.11/python.exe -B _scratch/dbg_rw.py
"""
import os
import sys
import tempfile
import marshal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pyvers import compile_source
from pyvers.decomp311 import Rewriter

SRC = (
    "def f(x):\n"
    "    try:\n"
    "        try:\n"
    "            return 1\n"
    "        finally:\n"
    "            x = 1\n"
    "    finally:\n"
    "        x = 2\n"
)

tmp = tempfile.mkdtemp()
pyc = os.path.join(tmp, "tl.pyc")
compile_source(SRC, pyc, version="3.11", dfile="<tl>")
with open(pyc, "rb") as fh:
    blob = fh.read()
# find payload: skip 16-byte header (magic4+flags4+mtime4+size4)
code = marshal.loads(blob[16:])
fn = [c for c in code.co_consts if hasattr(c, "co_code") and c.co_name == "f"][0]
print("=== ORIGINAL 3.11 f ===")
import dis
dis.dis(fn)
print("\n=== REWRITTEN (3.9-shape) f ===")
out = Rewriter(fn).run()
for i in out:
    arg = ""
    if i.arg is not None:
        arg = " arg=%r argval=%r" % (i.arg, i.argval)
    print("%3d off=%-4s %-16s%s" % (out.index(i), i.offset, i.opname, arg))
