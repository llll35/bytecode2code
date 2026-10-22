import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
all_codes = collect_code_objects(pyc_file.code)

for depth, code in all_codes:
    if getattr(code, 'co_name', '') == 'write_txt':
        print(f"=== Decompiling write_txt (depth={depth}) ===", file=sys.stderr)
        dec = Decompiler()
        src = dec.decompile(code)
        print(src)
        break
