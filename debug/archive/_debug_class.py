import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
all_codes = collect_code_objects(pyc_file.code)
for d, c in all_codes:
    if getattr(c, 'co_name', '') == 'ReciprocalAnalyzer':
        import dis as _dis
        print(f'=== ReciprocalAnalyzer class body ({len(c.co_code)} bytes) ===')
        for i in _dis.get_instructions(c):
            print(f'  off={i.offset:3d} idx={i.offset//2:3d} op={i.opname:25s} arg={i.arg} argval={repr(getattr(i, chr(97)+chr(114)+chr(103)+chr(118)+chr(97)+chr(108), None))[:60]}')
        print()
        dec = Decompiler()
        print('=== Decompiled ===')
        src = dec.decompile(c)
        print(src)
        break
