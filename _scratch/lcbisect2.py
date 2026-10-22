import sys, os, marshal, py_compile, tempfile, copy
sys.path.insert(0, r"D:\py\bytecode2code")
from bytecode2code import Disassembler
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

def run(stream, tag, code_obj=None):
    dec = Decompiler310(); dec.dis = ForceDis(stream)
    out = dec.decompile(code_obj if code_obj is not None else compile_code("3.9"))
    print("=== %s ===" % tag); print(out)

base = Disassembler().disassemble(compile_code("3.9"))
run(base, "3.9 native")
# mangle: 3.9 COMPARE_OP args should already be 0/1/3. Try removing RESUME.
c = [i for i in base if i.opname != "RESUME"]
run(c, "3.9 minus RESUME")
