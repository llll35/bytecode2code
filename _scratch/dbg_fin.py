"""Trace _collect_finally_body / _hide_escape_copies for one probe."""
import importlib, os, py_compile, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.cases import FLOW_PROBES
import ast as _ast

name = sys.argv[1]
source = FLOW_PROBES[name]
version = "%d.%d" % sys.version_info[:2]
pkg = "py%sDecompiler" % version.replace(".", "")
mod = importlib.import_module(pkg + ".decompiler")
cls = next(v for k, v in vars(mod).items()
         if isinstance(v, type) and hasattr(v, "_collect_finally_body"))
print("### class", cls.__name__)

orig = cls._collect_finally_body
def traced(self, code, instructions, try_end_idx, handler_start_idx):
    out = orig(self, code, instructions, try_end_idx, handler_start_idx)
    print("[collect_finally] try_end=%d handler=%d -> body=%d stmts resume=%s"
          % (try_end_idx, handler_start_idx, len(out[0]), out[1]))
    for i in range(max(0, try_end_idx - 1), min(len(instructions), handler_start_idx + 6)):
        print("    %3d %-26s %s %s" % (i, instructions[i].opname,
              instructions[i].argval, "<<pop" if i == try_end_idx else "",))
    return out
cls._collect_finally_body = traced

orig2 = cls._hide_escape_copies
def traced2(self, instructions, instr_start, try_end_idx, handler_start_idx):
    print("[hide_escape] instr_start=%d try_end=%d handler=%d" % (instr_start, try_end_idx, handler_start_idx))
    return orig2(self, instructions, instr_start, try_end_idx, handler_start_idx)
cls._hide_escape_copies = traced2

parser = importlib.import_module(pkg + ".pyc_parser")
with tempfile.TemporaryDirectory() as tmp:
    sp = os.path.join(tmp, "p.py"); pp = os.path.join(tmp, "p.pyc")
    open(sp, "w", encoding="utf-8").write(source)
    py_compile.compile(sp, cfile=pp, doraise=True)
    from tests.test_roundtrip import decompile_sample
    print("### decompiled")
    print(decompile_sample(pp))
