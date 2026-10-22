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

from bytecode2code.decompiler import Decompiler
dec = Decompiler()

# Monkey-patch to debug class body filtering
orig_call = dec._process_instruction
def patched_call(instr, instructions, idx, code, stack, stmts, is_module=False, limit=None):
    if instr.opname == "CALL_FUNCTION" and idx == 24:  # approx where class body CALL happens
        print(f"CALL_FUNCTION at idx={idx}, stack before: {len(stack)}")
    result = orig_call(instr, instructions, idx, code, stack, stmts, is_module, limit)
    if instr.opname == "CALL_FUNCTION" and idx == 24:
        print(f"CALL_FUNCTION at idx={idx}, stack after: {len(stack)}")
    return result
dec._process_instruction = patched_call

result = dec.decompile(parser.code)
print("=== DECOMPILED ===")
print(result)
print("=== END ===")
