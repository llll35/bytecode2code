import sys, ast
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
all_codes = collect_code_objects(pyc_file.code)

dec = Decompiler()

# Monkey-patch to trace all _handled_ranges changes
orig_emit = dec._emit_statements
call_count = [0]

def traced_emit(code, instructions, is_module=False, base_offset=0):
    cid = call_count[0]
    call_count[0] += 1
    name = getattr(code, 'co_name', '?')
    n = len(instructions)
    ranges_before = list(dec._handled_ranges)
    result = orig_emit(code, instructions, is_module=is_module, base_offset=base_offset)
    ranges_after = list(dec._handled_ranges)
    changes = []
    for r in ranges_after:
        if r not in ranges_before:
            changes.append(r)
    print(f"[{cid:3d}] name={name:25s} n={n:4d} base={base_offset:3d}  before={ranges_before}  changes={changes}  after_has={ranges_after}  stmts={len(result)}")
    return result

dec._emit_statements = traced_emit

print("=== Full module decompile ===")
src = dec.decompile(pyc_file.code)
print("\n=== OUTPUT ===")
print(src)
