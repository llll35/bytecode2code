"""Trace Decompiler311._collect_finally_body for d3_nested_finally (3 levels).

Run under embed_python/python-3.11/python.exe
"""
import os
import sys
import tempfile
import marshal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pyvers import compile_source
from pyvers.decomp311 import Decompiler311, Rewriter

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

d = Decompiler311()
orig = Decompiler311._collect_finally_body


def traced(self, c, instructions, try_end_idx, handler_start_idx):
    print("COLLECT try_end_idx=%s(%s) handler=%s(%s)"
          % (try_end_idx, instructions[try_end_idx].opname,
             handler_start_idx, instructions[handler_start_idx].opname))
    body, resume = orig(self, c, instructions, try_end_idx, handler_start_idx)
    print("   -> body=%s resume=%s handled_now=%s"
          % ([type(s).__name__ for s in body], resume,
             [h for h in self._handled_ranges]))
    return body, resume


Decompiler311._collect_finally_body = traced
print(d.decompile(fn))
