import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler, ASTNode
from bytecode2code.disassembler import Instruction
import ast

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
dec = Decompiler()

objects = collect_code_objects(pyc_file.code)

# Find _validate_input
for depth, obj in objects:
    if getattr(obj, 'co_name', '') == '_validate_input':
        code = obj
        break

instrs = dec.dis.disassemble(code)
for i, ins in enumerate(instrs):
    print(f"  [{i:3d}] off={ins.offset:3d} op={ins.opname:25s} arg={ins.arg} argval={repr(ins.argval)[:60]}")
print()
stmts = dec._emit_statements(code, instrs)
print(f"Number of statements: {len(stmts)}")
for i, s in enumerate(stmts):
    try:
        src = ast.unparse(s)
        print(f"  [{i}] {type(s).__name__}: {src}")
    except Exception as e:
        print(f"  [{i}] {type(s).__name__}: ERROR {e}")
        print(f"       AST: {ast.dump(s)}")
