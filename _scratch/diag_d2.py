"""Diagnose the d2_try_break decompilation step by step."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bytecode2code import Decompiler
import dis

SOURCE = (
    "def f(xs):\n"
    "    for x in xs:\n"
    "        try:\n"
    "            if x:\n"
    "                break\n"
    "        finally:\n"
    "            x = 0\n"
    "    return x\n"
)

co = compile(SOURCE, "<test>", "exec")
f_code = co.co_consts[0]
instructions = list(dis.get_instructions(f_code))

print("=== Instructions ===")
for i, inst in enumerate(instructions):
    print(f"  [{i:2d}] offset={inst.offset:4d} {inst.opname:25s} arg={inst.argval}")

d = Decompiler()

# Monkey-patch to trace关键 steps
orig_find_pop = Decompiler._find_pop_block
def traced_find_pop(self, instructions, setup_idx, target_offset):
    result = orig_find_pop(self, instructions, setup_idx, target_offset)
    print(f"\n  _find_pop_block(setup={setup_idx}, target={target_offset}) -> {result}")
    print(f"    instructions[{result}]: {instructions[result].opname} arg={instructions[result].argval}")
    handler_idx = self._find_target_idx(instructions, target_offset)
    print(f"    handler_start_idx = {handler_idx}")
    # Show what's between result and handler
    for j in range(result, min(handler_idx, len(instructions))):
        print(f"      [{j}] {instructions[j].opname} arg={instructions[j].argval}")
    return result
Decompiler._find_pop_block = traced_find_pop

orig_collect = Decompiler._collect_finally_body
def traced_collect(self, code, instructions, try_end_idx, handler_start_idx):
    print(f"\n  _collect_finally_body(try_end={try_end_idx}, handler={handler_start_idx})")
    for j in range(try_end_idx, min(handler_start_idx+5, len(instructions))):
        print(f"    [{j}] {instructions[j].opname} arg={instructions[j].argval}")
    result = orig_collect(self, code, instructions, try_end_idx, handler_start_idx)
    print(f"  -> body={result[0]}, resume={result[1]}, handled_ranges={self._handled_ranges}")
    return result
Decompiler._collect_finally_body = traced_collect

orig_process = Decompiler._process_instruction
def traced_process(self, instr, instructions, idx, code, stack, stmts, **kw):
    opname = instr.opname
    if opname in ("SETUP_FINALLY", "POP_BLOCK"):
        print(f"\n  [{idx}] {opname} <- entering handler")
        print(f"     exc_stack before: {[(b['instr_start'], b['except_target'], b['try_end_idx']) for b in self._exc_stack]}")
    ret = orig_process(self, instr, instructions, idx, code, stack, stmts, **kw)
    if opname in ("SETUP_FINALLY", "POP_BLOCK"):
        print(f"  [{idx}] {opname} -> consumed={ret}")
        print(f"     exc_stack after: {[(b['instr_start'], b['except_target'], b['try_end_idx']) for b in self._exc_stack]}")
        print(f"     stmts so far: {len(stmts)}")
    return ret
Decompiler._process_instruction = traced_process

src = d.decompile(f_code)
print(f"\n=== FINAL SOURCE ===\n{src}")
