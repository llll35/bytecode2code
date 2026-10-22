import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
all_codes = collect_code_objects(pyc_file.code)

# Find class body code (depth 1, name=ReciprocalAnalyzer)
class_code = None
for d, c in all_codes:
    if getattr(c, 'co_name', '') == 'ReciprocalAnalyzer':
        class_code = c
        break

print(f"Class code size: {len(class_code.co_code)}")
print(f"Class code names: {class_code.co_names}")
print(f"Class code consts: {class_code.co_consts[:5]}")

dec = Decompiler()
instrs = dec.dis.disassemble(class_code)
print(f"\nInstructions ({len(instrs)}):")
for i, inst in enumerate(instrs):
    print(f"  {i:3d} offset={inst.offset:3d}  {inst.opname:20s} {str(inst.argval):30s}")

print("\n=== Decompile class body in isolation ===")
body_stmts = dec._emit_statements(class_code, instrs, is_module=False)
print(f"Got {len(body_stmts)} statements:")
for s in body_stmts:
    print(f"  {type(s).__name__}: {ast.unparse(s) if hasattr(ast, 'unparse') else s}")
