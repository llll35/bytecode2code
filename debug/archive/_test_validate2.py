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
        fn = dec._decompile_function(c, '_validate_input')
        print('=== _validate_input stmts ===')
        for i, s in enumerate(fn.body):
            try:
                src = ast.unparse(s)
                print(f'[{i}] {src}')
            except Exception as e:
                print(f'[{i}] {type(s).__name__}: {e}')
        break
