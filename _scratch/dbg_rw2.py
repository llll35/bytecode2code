"""Dump original + rewritten stream for d3_nested_finally (3 levels) under 3.11."""
import os
import sys
import tempfile
import marshal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pyvers import compile_source
from pyvers.decomp311 import Rewriter
import dis

SRC = (
    "def f(x):\n"
    "    try:\n"
    "        try:\n"
    "            try:\n"
    "                return 1\n"
    "            finally:\n"
    "                x = 1\n"
    "        finally:\n"
    "            x = 2\n"
    "    finally:\n"
    "        x = 3\n"
)

tmp = tempfile.mkdtemp()
pyc = os.path.join(tmp, "nf.pyc")
compile_source(SRC, pyc, version="3.11", dfile="<nf>")
with open(pyc, "rb") as fh:
    blob = fh.read()
code = marshal.loads(blob[16:])
fn = [c for c in code.co_consts if hasattr(c, "co_code") and c.co_name == "f"][0]
print("=== ORIGINAL ===")
dis.dis(fn)
print("\n=== REWRITTEN ===")
out = Rewriter(fn).run()
for i in out:
    arg = "" if i.arg is None else " arg=%r argval=%r" % (i.arg, i.argval)
    print("%3d off=%-4s %-16s%s" % (out.index(i), i.offset, i.opname, arg))
