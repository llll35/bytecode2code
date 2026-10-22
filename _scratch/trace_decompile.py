"""Trace decompiler internals for failing cases."""
import ast
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyvers import compile_source, decompile
from bytecode2code import Decompiler as DecClass
import dis

D2_BREAK = (
    "def f(xs):\n"
    "    for x in xs:\n"
    "        try:\n"
    "            if x:\n"
    "                break\n"
    "        finally:\n"
    "            x = 0\n"
    "    return x\n"
)

CASE = D2_BREAK
version = sys.argv[1] if len(sys.argv) > 1 else "3.9"
tmp = tempfile.mkdtemp()
pyc = os.path.join(tmp, "test.pyc")
compile_source(CASE, pyc, version=version, dfile="<probe>")

co = compile(CASE, "<test>", "exec")
f_code = co.co_consts[0]

print(f"=== Python {version} ===")
dis.dis(f_code)

# Now run decompiler with tracing
print("\n=== Decompiler Trace ===")

orig_process = DecClass._process_instruction
def traced_process(self, instr, instructions, idx, code, stack, stmts, **kw):
    opname = instr.opname
    ret = orig_process(self, instr, instructions, idx, code, stack, stmts, **kw)
    print(f"  [{idx:3d}] {opname:25s} -> consumed={ret}, stmts={len(stmts)}, exc_stack={len(self._exc_stack)}, handled_ranges={[(s,e) for s,e in self._handled_ranges]}")
    return ret
DecClass._process_instruction = traced_process

orig_collect = DecClass._collect_finally_body
def traced_collect(self, code, instructions, try_end_idx, handler_start_idx):
    result = orig_collect(self, code, instructions, try_end_idx, handler_start_idx)
    print(f"  _collect_finally_body(try_end={try_end_idx}, handler={handler_start_idx}) -> body={len(result[0])} stmts, resume={result[1]}, handled_ranges added")
    return result
DecClass._collect_finally_body = traced_collect

orig_find_post = DecClass._find_post_handler_idx
def traced_find_post(self, instructions, pop_idx, handler_start_idx, target):
    result = orig_find_post(self, instructions, pop_idx, handler_start_idx, target)
    print(f"  _find_post_handler_idx(handler={handler_start_idx}, target={target}) -> {result}")
    return result
DecClass._find_post_handler_idx = traced_find_post

orig_continue_over = DecClass._continue_over_handler
def traced_continue(self, instructions, idx):
    result = orig_continue_over(self, instructions, idx)
    print(f"  _continue_over_handler(idx={idx}) -> cont={type(result[0]).__name__ if result[0] else None}, skip_to={result[1]}")
    return result
DecClass._continue_over_handler = traced_continue

orig_consume_back = DecClass._consume_back_edge
def traced_consume(self, instructions, idx):
    result = orig_consume_back(self, instructions, idx)
    print(f"  _consume_back_edge(idx={idx}) -> {result}")
    return result
DecClass._consume_back_edge = traced_consume

out = decompile(pyc)
print(f"\nSource:\n{out['source']}")
