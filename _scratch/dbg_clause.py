"""Scratch: trace the plain except-clause body read for a flow probe.

    embed_python/python-3.10/python.exe _scratch/dbg_clause.py finally_return
"""
import importlib
import os
import py_compile
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.cases import FLOW_PROBES

name = sys.argv[1]
source = FLOW_PROBES[name]
version = "%d.%d" % sys.version_info[:2]
pkg = "py%sDecompiler" % version.replace(".", "")
mod = importlib.import_module(pkg)
parser = importlib.import_module(pkg + ".pyc_parser")
dm = importlib.import_module(pkg + ".decompiler")

with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "p.py")
    pyc_path = os.path.join(tmp, "p.pyc")
    with open(src_path, "w", encoding="utf-8") as handle:
        handle.write(source)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)
    code = parser.PyCParser.parse_file(pyc_path).code

Base = dm.Decompiler
orig_parse = Base._parse_handler_body
orig_emit = Base._emit_statements


def traced_parse(self, code, instructions, body_start, as_setup_target,
                 as_setup_idx, fallback_reraise_idx):
    print("-- _parse_handler_body(body_start=%d, fallback=%s)" % (
        body_start, fallback_reraise_idx))
    print("   handled_ranges=%s" % (getattr(self, "_handled_ranges", None),))
    regions = self._exception_regions(instructions)
    for idx in sorted(regions):
        r = regions[idx]
        print("   region setup=%d kind=%s body=%s..%s pops=%s exit=%s" % (
            idx, r.kind, r.body_start, r.body_end, r.body_pops, r.exit_pops))
    out = orig_parse(self, code, instructions, body_start, as_setup_target,
                     as_setup_idx, fallback_reraise_idx)
    print("   -> post=%d %s" % (out[1], [type(s).__name__ for s in out[0]]))
    return out


def traced_emit(self, code, instructions, is_module=False, start=0,
                end=None, out_stack=None, *args, **kwargs):
    if end is None:
        end = len(instructions)
    before = len(out_stack) if out_stack is not None else -1
    res = orig_emit(self, code, instructions, is_module, start, end, out_stack,
                    *args, **kwargs)
    if 0 <= end - start <= 12 and start >= 15:
        print("   _emit_statements(%d,%d) -> %s  stack+%d" % (
            start, end, [type(s).__name__ for s in res],
            (len(out_stack) - before) if out_stack is not None else 0))
    return res


Base._parse_handler_body = traced_parse
Base._emit_statements = traced_emit
print(mod.decompile(code))
