"""Dump the CFG-derived regions for a probe, with the block-stack trace.

Run with the interpreter whose bytecode should be inspected:
  embed_python/python-3.10/python.exe _scratch/dbg21.py nested_finally_reraise
"""
import sys, os, dis
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests import cases
from py39Decompiler.cfg_flow import build_cfg, ExceptionAnalyzer, _SETUP_OPS, _BLOCK_POPS

name = sys.argv[1] if len(sys.argv) > 1 else "nested_finally_reraise"
src = dict(cases.FLOW_PROBES)[name] if hasattr(cases, "FLOW_PROBES") else None
if src is None:
    src = dict(cases.PROBES)[name]
code = compile(src, "<probe>", "exec")
while code.co_name != "f":
    code = [c for c in code.co_consts if hasattr(c, "co_code")][0]

from py39Decompiler.decompiler import Decompiler
d = Decompiler()
instrs = d._insert_dead_block_closes(d.dis.disassemble(code))
for i, ins in enumerate(instrs):
    print(i, ins.offset, ins.opname, ins.argval if ins.opname in
          ("LOAD_CONST", "LOAD_FAST", "LOAD_NAME", "CALL_FUNCTION") else ins.argrepr)
print("---- regions ----")
cfg = build_cfg(instrs)
an = ExceptionAnalyzer(instrs, cfg)
for r in an.regions():
    print("region setup", r.setup_index, r.setup_op, "->", r.handlers,
          "kind", r.kind, "body", r.body_start, r.body_end,
          "pops", r.body_pops, "last", r.last_body_pop)
