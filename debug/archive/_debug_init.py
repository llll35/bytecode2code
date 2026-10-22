import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser
from bytecode2code.decompiler import Decompiler, ASTNode
from bytecode2code.disassembler import Instruction
import dis as _dis

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
dec = Decompiler()
instrs = dec.dis.disassemble(pyc_file.code)

# Find the __init__ code object
for const in getattr(pyc_file.code, 'co_consts', ()):
    if hasattr(const, 'co_name') and const.co_name == '__init__':
        init_code = const
        break

print(f"__init__ code object: {init_code.co_name}")
print(f"co_code length: {len(init_code.co_code)}")
init_instrs = dec.dis.disassemble(init_code)
print(f"Number of instructions: {len(init_instrs)}")
print()
for i, ins in enumerate(init_instrs):
    print(f"  [{i:3d}] off={ins.offset:3d} op={ins.opname:25s} arg={ins.arg} argval={repr(ins.argval)[:60]}")
