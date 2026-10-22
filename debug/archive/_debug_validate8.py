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
        instrs = dec.dis.disassemble(c)

        # Monkey-patch _emit_statements to trace ALL calls
        original_emit = dec._emit_statements
        call_depth = [0]
        call_id = [0]

        def traced_emit(code, instructions, **kwargs):
            depth = call_depth[0]
            my_id = call_id[0]
            call_id[0] += 1
            call_depth[0] += 1
            prefix = "  " * depth
            base_offset = kwargs.get('base_offset', 0)
            print(f"{prefix}>>> CALL#{my_id} len={len(instructions)} base_off={base_offset} ranges={list(dec._handled_ranges)}")
            try:
                result = original_emit(code, instructions, **kwargs)
                # Print each statement
                for si, s in enumerate(result):
                    try:
                        srepr = ast.unparse(s)
                    except:
                        srepr = type(s).__name__
                    print(f"{prefix}    stmt[{si}]: {srepr}")
                print(f"{prefix}<<< CALL#{my_id} returned {len(result)} stmts ranges={list(dec._handled_ranges)}")
                return result
            finally:
                call_depth[0] -= 1

        dec._emit_statements = traced_emit

        fn = dec._decompile_function(c, '_validate_input')
        print("\n=== Result ===")
        for s in fn.body:
            try:
                print(ast.unparse(s))
            except:
                print(type(s).__name__)
        break
