import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
all_codes = collect_code_objects(pyc_file.code)

for depth, code in all_codes:
    if getattr(code, 'co_name', '') == 'write_txt':
        print(f"=== write_txt: {len(code.co_code)} bytes, {len(all_codes)} total codes ===", file=sys.stderr)
        import dis
        print(f"=== Instructions for write_txt ===", file=sys.stderr)
        for instr in dis.get_instructions(code):
            print(f"  offset={instr.offset:3d}  idx={instr.offset//2:3d}  {instr.opname:25s}  arg={instr.arg}", file=sys.stderr)
        break
