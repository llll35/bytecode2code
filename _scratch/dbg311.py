"""Dump the fake-3.9 stream produced by decomp311.Rewriter + its region table."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from py311Decompiler.decomp311 import Rewriter
from py311Decompiler import cfg_flow

SRC = (
    "def f(n):\n"
    "    try:\n"
    "        x = int(n)\n"
    "    except ValueError as e:\n"
    "        print(e)\n"
    "    else:\n"
    "        x += 1\n"
    "    finally:\n"
    "        print('done')\n"
    "    return x\n"
)

code = compile(SRC, "dbg.py", "exec")
f_code = code.co_consts[0]

stream = Rewriter(f_code).run()
print("=== rewritten stream ===")
for i, ins in enumerate(stream):
    print("%3d  %-28s %s" % (i, ins.opname, ins.argrepr))

print()
print("=== regions ===")
an = cfg_flow.ExceptionAnalyzer(stream)
for region in sorted(an.regions(), key=lambda r: r.setup_index):
    print(
        "setup %3d op=%-14s kind=%-7s body=[%s,%s) pops=%s exits=%s handlers=%s"
        % (
            region.setup_index,
            region.setup_op,
            region.kind,
            region.body_start,
            region.body_end,
            region.body_pops,
            region.exit_pops,
            region.handlers,
        )
    )
