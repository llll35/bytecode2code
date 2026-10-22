"""Trace _process_with on the running interpreter for a given source."""
import ast
import os
import sys
import py_compile
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser

SRC = "def f(a, b, c):\n    with a as x, b as y, c as z:\n        return x\n"

tmp = tempfile.mkdtemp()
p = os.path.join(tmp, "t.py")
pyc = os.path.join(tmp, "t.pyc")
with open(p, "w") as f:
    f.write(SRC)
py_compile.compile(p, cfile=pyc, doraise=True)
code = PyCParser.parse_file(pyc).code

dec = Decompiler()
orig = dec._process_with


def traced(instr, instructions, idx, code, stack, stmts):
    print("[with] enter idx=%d off=%d stack=%d" % (idx, instr.offset, len(stack)))
    res = orig(instr, instructions, idx, code, stack, stmts)
    print("[with] exit  idx=%d -> next=%d stack=%d" % (idx, idx + res, len(stack)))
    return res


dec._process_with = traced
orig_term = dec._with_exit_terminator


def traced_term(instructions, pop_idx, limit):
    r = orig_term(instructions, pop_idx, limit)
    print("    [term] pop=%d(%d) limit=%d -> %d (%s)" % (
        pop_idx, instructions[pop_idx].offset, limit, r,
        instructions[r].opname if 0 <= r < len(instructions) else "EOF"))
    return r


dec._with_exit_terminator = traced_term
orig_pop = dec._find_pop_block


def traced_pop(instructions, setup_idx, target):
    r = orig_pop(instructions, setup_idx, target)
    print("    [pop] setup=%d target=%d -> %d (off %d)" % (
        setup_idx, target, r, instructions[r].offset if r < len(instructions) else -1))
    return r


dec._find_pop_block = traced_pop

orig_rv = dec._with_return_value


def traced_rv(instructions, term_idx, body_stack):
    r = orig_rv(instructions, term_idx, body_stack)
    print("    [retval] term=%d body_stack=%s -> %r" % (
        term_idx, [ast.dump(e)[:30] for e in body_stack], r))
    return r


dec._with_return_value = traced_rv

print(dec.decompile(code))
