import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.disassembler import Disassembler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
all_codes = collect_code_objects(pyc_file.code)

for depth, code in all_codes:
    if getattr(code, 'co_name', '') == 'write_txt':
        dis = Disassembler()
        instructions = dis.disassemble(code, show_lineno=False)
        print(f"Total instructions: {len(instructions)}", file=sys.stderr)
        for i, instr in enumerate(instructions):
            print(f"  idx={i:3d}  offset={instr.offset:3d}  {instr.opname:25s}  arg={instr.arg}  argval={instr.argval}", file=sys.stderr)
        break
