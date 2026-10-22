import sys, os, marshal, py_compile, tempfile, ast
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers.decomp311 import Rewriter, Decompiler311
from pyvers.decomp_compat import Decompiler310

src = "def h(a, b, c, d, e):\n    r = a < b <= c != d is e\n    return r, not (a < b < c < d < e)\n"
d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
with open(pyc,"rb") as fh:
    fh.read(16); code = marshal.loads(fh.read())
fn = [c for c in code.co_consts if hasattr(c,"co_code")][0]
translated = Rewriter(fn).run()

class Fixed310(Decompiler310):
    def __init__(self, instrs):
        super().__init__()
        self._forced = instrs
        from pyvers.decomp311 import TranslatingDisassembler
        self.dis = TranslatingDisassembler()
    def _get_instructions(self, code):
        return self._forced

# Instead just directly patch dis
class ForceDis:
    def __init__(self, instrs): self.instrs = instrs
    def disassemble(self, code, show_lineno=True): return self.instrs
    def disassemble_to_str(self, code, show_header=True, show_lineno=True):
        return "\n".join(i.opname for i in self.instrs)

for cls in (Decompiler310, Decompiler311):
    dec = cls()
    dec.dis = ForceDis(translated)
    try:
        out = dec.decompile(fn)
        print("=== %s ===" % cls.__name__)
        print(out)
    except Exception as e:
        import traceback; print(cls.__name__, "ERR", e); traceback.print_exc()
