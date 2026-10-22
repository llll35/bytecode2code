import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser
from bytecode2code.decompiler import Decompiler, ASTNode
from bytecode2code.disassembler import Instruction
import dis as _dis

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
dec = Decompiler()

# Find _prime_factorization_25 code object
for const in getattr(pyc_file.code, 'co_consts', ()):
    if hasattr(const, 'co_name') and const.co_name == '_prime_factorization_25':
        code = const
        break

print(f"Code: {code.co_name}")
instrs = dec.dis.disassemble(code)
for i, ins in enumerate(instrs):
    print(f"  [{i:3d}] off={ins.offset:3d} op={ins.opname:25s} arg={ins.arg} argval={repr(ins.argval)[:60]}")
