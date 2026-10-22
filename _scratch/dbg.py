"""Trace the reader on a snippet, under the matching embedded interpreter.

usage: python _scratch\dbg.py <version> < file.py
"""
import ast
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from pyvers.decomp_compat import make_decompiler  # noqa: E402

version = sys.argv[1]
source = sys.stdin.read()
code = compile(source, "<probe>", "exec")

Base = make_decompiler(version).__class__


class Traced(Base):
    def _emit_statements(self, code, instructions, **kwargs):
        out = super()._emit_statements(code, instructions, **kwargs)
        if kwargs.get("start") is not None:
            print("  _emit_statements %s..%s -> %s" % (
                kwargs.get("start"), kwargs.get("end"),
                [type(s).__name__ for s in out]))
        return out

    def _process_with(self, instr, instructions, idx, code, stack, stmts):
        before = len(stmts)
        n = super()._process_with(instr, instructions, idx, code, stack, stmts)
        print("  _process_with at %s -> %s" % (
            instr.offset,
            ast.dump(stmts[before])[:90] if len(stmts) > before else "nothing"))
        return n


dec = Traced()
for const in code.co_consts:
    if hasattr(const, "co_code"):
        print("### %s ###" % const.co_name)
        print(dec.decompile(const))
