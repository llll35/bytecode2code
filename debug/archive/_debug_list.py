import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
dec = Decompiler()

objects = collect_code_objects(pyc_file.code)
print(f"Total code objects: {len(objects)}")
for depth, obj in objects:
    name = getattr(obj, 'co_name', '?')
    code_len = len(getattr(obj, 'co_code', b''))
    print(f"  depth={depth} name={name} code_len={code_len}")

# Find __init__
for depth, obj in objects:
    if getattr(obj, 'co_name', '') == '__init__':
        print(f"\n=== __init__ instructions ===")
        instrs = dec.dis.disassemble(obj)
        for i, ins in enumerate(instrs):
            print(f"  [{i:3d}] off={ins.offset:3d} op={ins.opname:25s} arg={ins.arg} argval={repr(ins.argval)[:60]}")
