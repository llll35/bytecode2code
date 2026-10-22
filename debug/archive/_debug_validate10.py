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

        def traced_emit(code, instructions, **kwargs):
            base_offset = kwargs.get('base_offset', 0)
            print(f">>> _emit_statements len={len(instructions)} base_off={base_offset} ranges={list(dec._handled_ranges)}")
            try:
                result = original_emit(code, instructions, **kwargs)
                print(f"<<< returned {len(result)} stmts, ranges now={list(dec._handled_ranges)}")
                return result
            finally:
                pass

        dec._emit_statements = traced_emit

        # Monkey-patch _process_instruction to trace every instruction in CALL#0
        original_process = dec._process_instruction

        def traced_process(instr, instructions, idx, code, stack, stmts, **kwargs):
            base_offset = kwargs.get('base_offset', 0)
            handled = any(start <= base_offset + idx < end for start, end in dec._handled_ranges)
            if handled:
                print(f"  SKIP idx={idx} {instr.opname} (handled)")
                return 1
            result = original_process(instr, instructions, idx, code, stack, stmts, **kwargs)
            if instr.opname in ("POP_BLOCK", "RETURN_VALUE", "JUMP_FORWARD", "SETUP_FINALLY", "RERAISE", "RAISE_VARARGS"):
                print(f"  OP idx={idx} {instr.opname} consumed={result} ranges={list(dec._handled_ranges)}")
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
