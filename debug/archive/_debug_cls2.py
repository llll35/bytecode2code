import ast, dis, sys
sys.path.insert(0, r'D:\py\bytecode2code')

# Create the full test case with S defined
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
import importlib.util
spec = importlib.util.spec_from_file_location('debug_cls', r'D:\py\bytecode2code\_debug_cls.pyc')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Find the T class code object
import bytecode2code.pyc_parser as pp
parser = pp.PyCParser.parse_file(r'D:\py\bytecode2code\_debug_cls.pyc')
print("Main code:", parser.code.co_name)
for i, c in enumerate(parser.code.co_consts):
    if hasattr(c, 'co_name'):
        print(f"  const[{i}]: {c.co_name} flags={c.co_flags:#x} cellvars={c.co_cellvars} freevars={c.co_freevars}")
        dis.dis(c)
        print()

# Now decompile
from bytecode2code.decompiler import Decompiler
dec = Decompiler()
result = dec.decompile(parser.code)
print("=== DECOMPILED ===")
print(result)
print("=== END ===")
