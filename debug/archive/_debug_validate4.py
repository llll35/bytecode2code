import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
all_codes = collect_code_objects(pyc_file.code)

for d, c in all_codes:
    if getattr(c, 'co_name', '') == '_validate_input':
        dec = Decompiler()
        instrs = dec.dis.disassemble(c)
        print(f"Instructions ({len(instrs)}):")
        for i, inst in enumerate(instrs):
            print(f"  {i:3d} offset={inst.offset:3d}  {inst.opname:20s} arg={inst.arg!r:6s}  argval={str(inst.argval)[:35]}")

        # Monkey-patch _emit_statements to trace
        original_emit = dec._emit_statements

        def traced_emit(code, instructions, **kwargs):
            print(f"\n>>> _emit_statements called, len(instructions)={len(instructions)}, handled_ranges={list(dec._handled_ranges)}")
            result = original_emit(code, instructions, **kwargs)
            print(f"<<< _emit_statements done, new handled_ranges={list(dec._handled_ranges)}, stmts emitted={len(result)}")
            for s in result:
                print(f"    stmt: {ast.dump(s) if hasattr(dec.ast, 'dump') else type(s).__name__}")
            return result

        import ast
        dec._emit_statements = traced_emit

        fn = dec._decompile_function(c, '_validate_input')
        print("\n=== Result ===")
        print(ast.unparse(fn))
        break
