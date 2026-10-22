"""Direct decompiler trace for failing cases."""
import ast
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bytecode2code import Decompiler
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

co = compile(D2_BREAK, "<test>", "exec")
f_code = co.co_consts[0]

print("=== Bytecode ===")
dis.dis(f_code)

# Build instruction list manually
instructions = list(dis.get_instructions(f_code))
for i, inst in enumerate(instructions):
    print(f"  [{i:2d}] offset={inst.offset:4d} {inst.opname:25s} arg={inst.argval}")

print("\n=== Direct Decompiler Trace ===")
d = Decompiler()

# Monkey-patch
orig_process = Decompiler._process_instruction
def traced_process(self, instr, instructions, idx, code, stack, stmts, **kw):
    opname = instr.opname
    ret = orig_process(self, instr, instructions, idx, code, stack, stmts, **kw)
    print(f"  [{idx:3d}] {opname:25s} -> consumed={ret}, stmts={len(stmts)}, exc_stack={len(self._exc_stack)}, handled={self._handled_ranges[:]}")
    return ret
Decompiler._process_instruction = traced_process

orig_collect = Decompiler._collect_finally_body
def traced_collect(self, code, instructions, try_end_idx, handler_start_idx):
    result = orig_collect(self, code, instructions, try_end_idx, handler_start_idx)
    print(f"  _collect_finally_body(try_end={try_end_idx}, handler={handler_start_idx}) -> body={len(result[0])}, resume={result[1]}, handled={self._handled_ranges}")
    return result
Decompiler._collect_finally_body = traced_collect

orig_find_post = Decompiler._find_post_handler_idx
def traced_find_post(self, instructions, pop_idx, handler_start_idx, target):
    result = orig_find_post(self, instructions, pop_idx, handler_start_idx, target)
    print(f"  _find_post_handler_idx(handler={handler_start_idx}, target={target}) -> {result}")
    return result
Decompiler._find_post_handler_idx = traced_find_post

orig_continue_over = Decompiler._continue_over_handler
def traced_continue(self, instructions, idx):
    result = orig_continue_over(self, instructions, idx)
    print(f"  _continue_over_handler(idx={idx}) -> cont={type(result[0]).__name__ if result[0] else None}, skip_to={result[1]}")
    return result
Decompiler._continue_over_handler = traced_continue

orig_consume_back = Decompiler._consume_back_edge
def traced_consume(self, instructions, idx):
    result = orig_consume_back(self, instructions, idx)
    print(f"  _consume_back_edge(idx={idx}) -> {result}")
    return result
Decompiler._consume_back_edge = traced_consume

src = d.decompile(f_code)
print(f"\nSource:\n{src}")
