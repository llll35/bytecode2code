import sys, dis
sys.path.insert(0, r'D:\py\bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler

code = PyCParser.parse_file(r'D:\py\bytecode2code\bytecode2code\checkerboard.cpython-39.pyc').code
target = None
for path, c in collect_code_objects(code):
    if c.co_name == '_get_count_on_direction':
        target = c
        break

dec = Decompiler()
instrs = dec.dis.disassemble(target)

orig_for = dec._process_for_iter if hasattr(dec, '_process_for_iter') else None

# Instrument FOR_ITER
import bytecode2code.decompiler as dm
opnames = [i.opname for i in instrs]
for k, op in enumerate(opnames):
    if op == 'FOR_ITER':
        print(f'FOR_ITER at idx {k} offset {instrs[k].offset} target {instrs[k].argval}')

# Trace _emit_statements top-level decisions
orig_emit = Decompiler._emit_statements
depth = {'d': 0}
def traced(self, code, instructions, is_module=False, start=0, end=None, out_stack=None):
    pad = '  ' * depth['d']
    print(f'{pad}EMIT range [{start}, {end})')
    depth['d'] += 1
    try:
        return orig_emit(self, code, instructions, is_module=is_module, start=start, end=end, out_stack=out_stack)
    finally:
        depth['d'] -= 1
Decompiler._emit_statements = traced

orig_for_iter = None
for name in dir(dec):
    pass

stmts = dec._emit_statements(target, instrs, is_module=False)
print()
print('=== RESULT ===')
import ast
print(ast.unparse(ast.Module(body=stmts, type_ignores=[])))
