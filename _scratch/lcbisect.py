import sys, os, marshal, py_compile, tempfile
sys.path.insert(0, r"D:\py\bytecode2code")
from bytecode2code import Disassembler
from pyvers.decomp311 import Rewriter
from pyvers.decomp_compat import Decompiler310

src = "def h(a, b, c, d, e):\n    r = a < b <= c != d is e\n    return r, not (a < b < c < d < e)\n"

class ForceDis:
    def __init__(self, instrs): self.instrs = instrs
    def disassemble(self, code, show_lineno=True): return self.instrs
    def disassemble_to_str(self, code, show_header=True, show_lineno=True):
        return "\n".join(i.opname for i in self.instrs)

def compile_code(ver):
    d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
    pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
    with open(pyc,"rb") as fh:
        fh.read(16); code = marshal.loads(fh.read())
    return [c for c in code.co_consts if hasattr(c,"co_code")][0]

def run(stream, tag):
    dec = Decompiler310(); dec.dis = ForceDis(stream)
    out = dec.decompile(compile_code("3.12"))
    print("=== %s ===" % tag); print(out)
    return out

b = Rewriter(compile_code("3.12")).run()
run(b, "as translated")

# Try: set every instruction's offset-independent fields to the 3.9 equivalents
# by comparing opnames.
import copy
for ins in b:
    if ins.opname == "COMPARE_OP":
        pass
# Test 1: reset line_no to None everywhere
c = copy.deepcopy(b)
for ins in c: ins.line_no = None
run(c, "line_no=None all")

# Test 2: reset is_jump_target
c = copy.deepcopy(b)
for ins in c: ins.is_jump_target = False
run(c, "is_jump_target=False all")
