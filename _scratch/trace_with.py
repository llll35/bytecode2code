"""Trace _process_with for the 3.12 multi-with sample."""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from pyvers import decomp311, worker
from pyvers.pycfile import read_header

SRC = "def f(a, b):\n    with a as x, b as y:\n        return x + y\n"

import tempfile, py_compile, ast

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
dec = decomp311.Decompiler311()

orig = dec._process_with


def traced(instr, instructions, idx, code, stack, stmts):
    print("[with] enter idx=%d op=%s offset=%d stack=%d" % (
        idx, instr.opname, instr.offset, len(stack)))
    res = orig(instr, instructions, idx, code, stack, stmts)
    print("[with] exit  idx=%d -> merge=%d (next=%d) stmts_now=%d stack=%d" % (
        idx, res, idx + res, len(stmts), len(stack)))
    for s in stmts:
        print("       stmt:", ast.dump(s)[:100])
    return res


dec._process_with = traced

orig_exit_term = dec._with_exit_terminator


def traced_term(instructions, pop_idx, limit):
    r = orig_exit_term(instructions, pop_idx, limit)
    print("    [term] pop_idx=%d limit=%d -> %d (%s)" % (
        pop_idx, limit, r,
        instructions[r].opname if 0 <= r < len(instructions) else "EOF"))
    return r


dec._with_exit_terminator = traced_term

orig_stmt_run = dec._find_stmt_run_end


def traced_run(instructions, start, hard_end):
    r = orig_stmt_run(instructions, start, hard_end)
    print("    [run_end] start=%d hard_end=%d -> %d" % (start, hard_end, r))
    return r


dec._find_stmt_run_end = traced_run

print(dec.decompile(target))
