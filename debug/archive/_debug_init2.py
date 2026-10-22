import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler, ASTNode
from bytecode2code.disassembler import Instruction
import ast

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
dec = Decompiler()

objects = collect_code_objects(pyc_file.code)

# Find __init__
for depth, obj in objects:
    if getattr(obj, 'co_name', '') == '__init__':
        init_code = obj
        break

instrs = dec.dis.disassemble(init_code)
stmts = dec._emit_statements(init_code, instrs)
print(f"Number of statements: {len(stmts)}")
for i, s in enumerate(stmts):
    try:
        src = ast.unparse(s)
        print(f"  [{i}] {type(s).__name__}: {src}")
    except Exception as e:
        print(f"  [{i}] {type(s).__name__}: ERROR {e}")
        # dump the AST
        print(f"       AST: {ast.dump(s)}")
