import ast, dis, sys
sys.path.insert(0, r'D:\py\bytecode2code')

src = '''class S:
    pass
class T(S):
    def norm(self):
        return super().norm * 2
'''
with open(r'D:\py\bytecode2code\_debug_cls.py', 'w') as f:
    f.write(src)
import py_compile
py_compile.compile(r'D:\py\bytecode2code\_debug_cls.py', cfile=r'D:\py\bytecode2code\_debug_cls.pyc', doraise=True)
import bytecode2code.pyc_parser as pp
parser = pp.PyCParser.parse_file(r'D:\py\bytecode2code\_debug_cls.pyc')

# Find the T class body code object (const[2])
t_code = None
for i, c in enumerate(parser.code.co_consts):
    if hasattr(c, 'co_name') and c.co_name == 'T':
        t_code = c
        break

print("T code object co_consts:")
for i, c in enumerate(t_code.co_consts):
    if hasattr(c, 'co_name'):
        print(f"  const[{i}]: {c.co_name}")

from bytecode2code.decompiler import Decompiler
dec = Decompiler()
dis.dis(t_code)
print()

# Now manually emit statements for T
from bytecode2code.disassembler import Instruction
instructions = dec.dis.disassemble(t_code)
print(f"\nTotal instructions: {len(instructions)}")
for i, ins in enumerate(instructions):
    print(f"  [{i:2d}] {ins.offset:4d}: {ins.opname} {ins.argval!r:30s} arg={ins.arg}")

# Emit with is_module=False
stmts = dec._emit_statements(t_code, instructions, is_module=False)
print(f"\nEmitted {len(stmts)} statements:")
for s in stmts:
    print(f"  {type(s).__name__}: {ast.dump(s)[:100]}")

# Now filter
filtered = [
    s for s in stmts
    if not (isinstance(s, ast.Return) and (s.value is None or (isinstance(s.value, ast.Constant) and s.value.value is None)))
]
print(f"\nAfter first filter: {len(filtered)} statements")
for s in filtered:
    print(f"  {type(s).__name__}: {ast.dump(s)[:100]}")
