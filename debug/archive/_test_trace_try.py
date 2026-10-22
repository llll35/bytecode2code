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

        # Print instructions 16-47 (the try body of outer SETUP_FINALLY)
        print("=== Try body instructions (outer SETUP_FINALLY) ===")
        for i in range(16, 48):
            inst = instrs[i]
            abs_idx = i
            print(f"  inner_idx={i-16:2d} abs_idx={abs_idx:2d} byte={inst.offset:3d} {inst.opname}{' '+str(inst.arg) if inst.arg else ''}")

        # Show the nested try block within the try body
        print("\n=== Instructions with SETUP_FINALLY in try body ===")
        for i in range(16, 48):
            if instrs[i].opname in ("SETUP_FINALLY", "SETUP_EXCEPT", "POP_BLOCK", "POP_EXCEPT"):
                print(f"  idx={i} {instrs[i].opname} arg={instrs[i].arg}")

        # Now manually trace: what is base_offset=1 trying body?
        try_instrs = instrs[17:49]  # instructions[16+1 : handler_start_idx]
        print(f"\n=== CALL#4 inputs: {len(try_instrs)} instructions, base_offset=1 ===")
        for i, inst in enumerate(try_instrs):
            print(f"  inner_idx={i:2d} orig_idx={i+17:2d} byte={inst.offset:3d} {inst.opname}{' '+str(inst.arg) if inst.arg else ''}")
        break
