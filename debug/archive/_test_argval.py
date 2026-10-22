import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler
import dis as pydis

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
all_codes = collect_code_objects(pyc_file.code)

for d, c in all_codes:
    if getattr(c, 'co_name', '') == '_validate_input':
        print("=== Python dis.dis ===")
        pydis.dis(c)
        print("\n=== Custom disassemble ===")
        dec = Decompiler()
        instrs = dec.dis.disassemble(c)
        for i, inst in enumerate(instrs):
            print(f"idx={i:2d} byte={inst.offset:3d} {inst.opname:25s} arg={inst.arg!r:10s} argval={inst.argval!r:20s} argrepr={inst.argrepr!r}")
        break
