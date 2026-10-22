import sys
sys.path.insert(0, r'd:\py\bytecode2code')

from bytecode2code.pyc_parser import PyCParser
from bytecode2code.decompiler import Decompiler
import dis

pyc_file = PyCParser.parse_file(r'd:\py\bytecode2code\tests\samples\prime.pyc')
orig_code = pyc_file.code

def find_code(co, name):
    for const in co.co_consts:
        if isinstance(const, type(co)):
            if const.co_name == name:
                return const
            result = find_code(const, name)
            if result:
                return result
    return None

orig = find_code(orig_code, '_validate_input')
instrs = list(dis.get_instructions(orig))

print("=== Tracing decompiler behavior ===")
print()

dec = Decompiler()

# Run decompiler with tracing
result = dec.decompile(orig_code)
print("Decompiled source:")
print(result)
print()

# Now recompile and compare
import tempfile, os
tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8')
tmp.write(result)
tmp.close()

try:
    src = open(tmp.name, encoding='utf-8').read()
    co2 = compile(src, tmp.name, 'exec')
    decompiled = find_code(co2, '_validate_input')
    print("=== Decompiled bytecode (after recompile) ===")
    dis.dis(decompiled)
finally:
    os.unlink(tmp.name)

print()
print("=== Comparing instructions ===")
orig_instrs = list(dis.get_instructions(orig))
decomp_instrs = list(dis.get_instructions(decompiled))

for i, (oi, di) in enumerate(zip(orig_instrs, decomp_instrs)):
    if oi.offset != di.offset or oi.opname != di.opname or oi.argval != di.argval or oi.arg != di.arg:
        print(f"Diff at idx {i}: orig={oi.offset} {oi.opname} {oi.argval!r} arg={oi.arg} vs decomp={di.offset} {di.opname} {di.argval!r} arg={di.arg}")

if len(orig_instrs) != len(decomp_instrs):
    print(f"Length diff: orig={len(orig_instrs)} decomp={len(decomp_instrs)}")
