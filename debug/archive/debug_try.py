import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser
from bytecode2code.disassembler import Disassembler
from bytecode2code.decompiler import Decompiler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
d = Disassembler()
instructions = d.disassemble(pyc_file.code)

dec = Decompiler()

# Simulate SETUP_FINALLY at index 14
setup_idx = 14
instr = instructions[setup_idx]
target = int(instr.argval)
try_end_idx = dec._find_pop_block(instructions, setup_idx, target)
print(f"SETUP_FINALLY at idx={setup_idx}, target={target}, try_end_idx={try_end_idx}")
print(f"try body: indices {setup_idx+1} to {try_end_idx-1}")

# Check what _emit_statements produces for try body
try_instrs = instructions[setup_idx+1:try_end_idx]
print(f"try_instrs count: {len(try_instrs)}")
for i, ti in enumerate(try_instrs):
    print(f"  try_instrs[{i}] offset={ti.offset} {ti.opname}")

try_body = dec._emit_statements(pyc_file.code, try_instrs, is_module=True)
print(f"try_body stmts: {len(try_body)}")
for s in try_body:
    print(f"  {s}")
