import sys, dis
sys.path.insert(0, r'D:\py\bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects

code = PyCParser.parse_file(r'D:\py\bytecode2code\bytecode2code\checkerboard.cpython-39.pyc').code
target = sys.argv[1] if len(sys.argv) > 1 else '_get_count_on_direction'
for path, c in collect_code_objects(code):
    if c.co_name == target:
        print("== path:", path, "flags=%#x" % c.co_flags)
        print("varnames:", c.co_varnames, "cellvars:", c.co_cellvars, "freevars:", c.co_freevars)
        dis.dis(c)
        print()
