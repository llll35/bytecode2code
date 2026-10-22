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

        # Trace POP_BLOCK handler specifically
        original_process = dec._process_instruction

        def traced_process(instr, instructions, idx, code, stack, stmts, **kwargs):
            if instr.opname == "POP_BLOCK":
                print(f"\n=== POP_BLOCK at idx={idx} ===")
                print(f"  exc_stack before: {dec._exc_stack}")
                print(f"  handled_ranges before: {list(dec._handled_ranges)}")
            result = original_process(instr, instructions, idx, code, stack, stmts, **kwargs)
            if instr.opname == "POP_BLOCK":
                print(f"  exc_stack after: {dec._exc_stack}")
                print(f"  handled_ranges after: {list(dec._handled_ranges)}")
                print(f"  skip returned: {result}")
            return result

        dec._process_instruction = traced_process

        fn = dec._decompile_function(c, '_validate_input')
        print("\n=== Result ===")
        print(ast.unparse(fn))
        break
