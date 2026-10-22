import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
all_codes = collect_code_objects(pyc_file.code)
for d, c in all_codes:
    n = getattr(c, 'co_name', '?')
    sz = len(getattr(c, 'co_code', b''))
    print(f'{d:2d}  name={n:30s}  size={sz}')

print()
print('=== Full module decompile ===')
dec = Decompiler()
src = dec.decompile(pyc_file.code)
print(src)
