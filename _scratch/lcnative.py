import sys, os, marshal, py_compile, tempfile
sys.path.insert(0, r"D:\py\bytecode2code")
from bytecode2code import Instruction, Disassembler
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

version = sys.argv[1]
fn = compile_code(version)
if version == "3.9":
    stream = Disassembler().disassemble(fn)
else:
    stream = Rewriter(fn).run()
dec = Decompiler310(); dec.dis = ForceDis(stream)
print("=== %s ===" % version)
print(dec.decompile(fn))
