import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser
from bytecode2code.disassembler import Disassembler
from bytecode2code.decompiler import Decompiler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
d = Disassembler()
instructions = d.disassemble(pyc_file.code)

dec = Decompiler()

# Simulate what happens at SETUP_FINALLY (index 14)
setup_idx = 14
instr = instructions[setup_idx]
print(f"SETUP_FINALLY at index={setup_idx} offset={instr.offset}")
target = 62  # instr.argval
skip_end = dec._find_finally_skip_end(instructions, setup_idx, target)
print(f"  target offset={target}, skip_end={skip_end}")
print(f"  consumed = {skip_end - setup_idx}")
print(f"  next i = {setup_idx + (skip_end - setup_idx)}")
print()

# Show try body instructions
try_end_idx = dec._find_target_idx(instructions, target)
print(f"  try_end_idx={try_end_idx} (offset={instructions[try_end_idx].offset})")
print(f"  try body: indices {setup_idx+1} to {try_end_idx-1}")
for i in range(setup_idx+1, try_end_idx):
    print(f"    [{i}] offset={instructions[i].offset:3d} {instructions[i].opname}")
print()

# Show except handler instructions
print(f"  except handler: indices {try_end_idx} to {skip_end-1}")
for i in range(try_end_idx, skip_end):
    print(f"    [{i}] offset={instructions[i].offset:3d} {instructions[i].opname}")
print()

# Show what _emit_statements produces for try body
try_instrs = instructions[setup_idx+1:try_end_idx]
try_body = dec._emit_statements(pyc_file.code, try_instrs, is_module=True)
print(f"  try_body: {len(try_body)} stmts")
for s in try_body:
    print(f"    {s}")

# Show what _emit_statements produces for except handler
except_instrs = dec._collect_except_handler(instructions, target)
print(f"  except_instrs: {len(except_instrs)} instrs")
exc_stmts = dec._emit_statements(pyc_file.code, except_instrs, is_module=True)
print(f"  exc_stmts: {len(exc_stmts)} stmts")
for s in exc_stmts:
    print(f"    {s}")
