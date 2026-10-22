import sys, ast
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
all_codes = collect_code_objects(pyc_file.code)

class_code = None
for d, c in all_codes:
    if getattr(c, 'co_name', '') == 'ReciprocalAnalyzer':
        class_code = c
        break

dec = Decompiler()
instrs = dec.dis.disassemble(class_code)

# Monkey-patch to trace
orig_emit = dec._emit_statements

def traced_emit(code, instructions, is_module=False, base_offset=0):
    n = len(instructions)
    print(f"\n--- _emit_statements called: n={n}, is_module={is_module}, base_offset={base_offset} ---")
    print(f"  handled_ranges before: {dec._handled_ranges}")
    result = orig_emit(code, instructions, is_module=is_module, base_offset=base_offset)
    print(f"  handled_ranges after: {dec._handled_ranges}")
    print(f"  statements produced: {len(result)}")
    for s in result:
        try:
            print(f"    {ast.unparse(s)}")
        except:
            print(f"    {type(s).__name__}")
    return result

dec._emit_statements = traced_emit

print("=== Full module decompile ===")
src = dec.decompile(pyc_file.code)
print("\n=== OUTPUT ===")
print(src)
