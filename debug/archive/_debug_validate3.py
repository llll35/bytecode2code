import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler
import dis as dis_mod

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
all_codes = collect_code_objects(pyc_file.code)

for d, c in all_codes:
    if getattr(c, 'co_name', '') == '_validate_input':
        print(f"_validate_input code size: {len(c.co_code)}")
        dec = Decompiler()
        instrs = dec.dis.disassemble(c)
        print(f"Instructions ({len(instrs)}):")
        for i, inst in enumerate(instrs):
            print(f"  {i:3d} offset={inst.offset:3d}  {inst.opname:20s} arg={inst.arg!r:6s}  argval={str(inst.argval)[:35]}")

        # Find SETUP_FINALLY at idx 15
        setup_idx = None
        for i, inst in enumerate(instrs):
            if inst.opname == "SETUP_FINALLY":
                setup_idx = i
                break
        if setup_idx is not None:
            target = int(instrs[setup_idx].argval if instrs[setup_idx].argval is not None else (instrs[setup_idx].arg or 0))
            print(f"\nSETUP_FINALLY at idx={setup_idx}, target offset={target}")

            handler_start_idx = dec._find_target_idx(instrs, target)
            print(f"Handler starts at idx={handler_start_idx}")
            for i in range(handler_start_idx, len(instrs)):
                inst = instrs[i]
                print(f"  {i:3d} offset={inst.offset:3d}  {inst.opname:20s} arg={inst.arg!r:6s}  argval={str(inst.argval)[:35]}")
        break
