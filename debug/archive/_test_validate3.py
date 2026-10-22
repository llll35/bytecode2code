import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler
import ast

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
all_codes = collect_code_objects(pyc_file.code)

for d, c in all_codes:
    if getattr(c, 'co_name', '') == '_validate_input':
        dec = Decompiler()
        # Monkey-patch to trace CALL#3
        original_emit = dec._emit_statements
        call_count = [0]

        def traced_emit(code, instructions, **kwargs):
            base_offset = kwargs.get('base_offset', 0)
            call_count[0] += 1
            cid = call_count[0]
            print(f"\n>>> CALL#{cid} len={len(instructions)} base_off={base_offset}")
            result = original_emit(code, instructions, **kwargs)
            print(f"<<< CALL#{cid} returned {len(result)} stmts")
            for si, s in enumerate(result):
                try:
                    src = ast.unparse(s)
                    print(f"    stmt[{si}]: {repr(src[:80])}")
                except Exception as e:
                    print(f"    stmt[{si}]: {type(s).__name__} -> {e}")
            return result

        dec._emit_statements = traced_emit
        fn = dec._decompile_function(c, '_validate_input')
        print("\n=== Result ===")
        for i, s in enumerate(fn.body):
            try:
                print(ast.unparse(s))
            except Exception as e:
                print(f"[{i}] {type(s).__name__}: {e}")
        break
