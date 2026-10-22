import sys, os, marshal, py_compile, tempfile, dis
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers.decomp311 import Rewriter
from pyvers.decomp_compat import Decompiler310

src = "def h(a, b, c, d, e):\n    r = a < b <= c != d is e\n    return r, not (a < b < c < d < e)\n"
d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
with open(pyc,"rb") as fh:
    fh.read(16); code = marshal.loads(fh.read())
fn = [c for c in code.co_consts if hasattr(c,"co_code")][0]
translated = Rewriter(fn).run()

# 3.12 compare opcode -> 3.9 arg index (bit 4 is a flag)
CMP = {'<':0,'<=':1,'==':2,'!=':3,'>':4,'>=':5}
for ins in translated:
    if ins.opname == 'COMPARE_OP' and isinstance(ins.argval, str):
        ins.arg = CMP.get(ins.argval, ins.arg)

class ForceDis:
    def __init__(self, instrs): self.instrs = instrs
    def disassemble(self, code, show_lineno=True): return self.instrs
    def disassemble_to_str(self, code, show_header=True, show_lineno=True):
        return "\n".join(i.opname for i in self.instrs)

dec = Decompiler310(); dec.dis = ForceDis(translated)
print(dec.decompile(fn))
