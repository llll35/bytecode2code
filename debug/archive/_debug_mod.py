import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
all_codes = collect_code_objects(pyc_file.code)

# Find module code
mod_code = None
for d, c in all_codes:
    if getattr(c, 'co_name', '') == '<module>':
        mod_code = c
        break

dec = Decompiler()
instrs = dec.dis.disassemble(mod_code)
print(f"Module instructions ({len(instrs)}):")
for i, inst in enumerate(instrs):
    print(f"  {i:3d} offset={inst.offset:3d}  {inst.opname:20s} {str(inst.argval):40s}")
