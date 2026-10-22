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

        # Trace _emit_statements
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
            print(f"{prefix}>>> CALL#{my_id} len={len(instructions)} base_off={base_offset}")
            try:
                result = original_emit(code, instructions, **kwargs)
                for si, s in enumerate(result):
                    try:
                        srepr = ast.unparse(s)
                    except:
                        srepr = type(s).__name__
                    print(f"{prefix}    stmt[{si}]: {srepr}")
                print(f"{prefix}<<< CALL#{my_id} returned {len(result)}")
                return result
            finally:
                call_depth[0] -= 1

        dec._emit_statements = traced_emit

        # Also trace _process_instruction to see what idx each instruction gets
        original_process = dec._process_instruction

        def traced_process(instr, instructions, idx, code, stack, stmts, **kwargs):
            if instr.opname in ("POP_BLOCK", "RETURN_VALUE", "JUMP_FORWARD"):
                print(f"  >>> process {instr.opname} at idx={idx}, exc_stack={len(dec._exc_stack)}, ranges={list(dec._handled_ranges)}")
            result = original_process(instr, instructions, idx, code, stack, stmts, **kwargs)
            if instr.opname in ("POP_BLOCK", "RETURN_VALUE", "JUMP_FORWARD"):
                print(f"  <<< process {instr.opname} at idx={idx}, consumed={result}")
            return result

        dec._process_instruction = traced_process

        fn = dec._decompile_function(c, '_validate_input')
        print("\n=== Result ===")
        for s in fn.body:
            try:
                print(ast.unparse(s))
            except:
                print(type(s).__name__)
        break
