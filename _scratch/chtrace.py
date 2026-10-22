import sys, os, marshal, py_compile, tempfile
sys.path.insert(0, r"D:\py\bytecode2code")
from bytecode2code import Decompiler as Base
from pyvers.decomp311 import Rewriter
src = "def f(a,b,c,d):\n    return a < b < c < d\n"
d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
with open(pyc,"rb") as fh:
    fh.read(16); code = marshal.loads(fh.read())
fn = [c for c in code.co_consts if hasattr(c,"co_code")][0]
tl = Rewriter(fn).run()
class ForceDis:
    def __init__(self, instrs): self.instrs = instrs
    def disassemble(self, code, show_lineno=True): return self.instrs
    def disassemble_to_str(self, code, show_header=True, show_lineno=True):
        return "\n".join(i.opname for i in self.instrs)

orig_pvc = Base._parse_value_chain
def traced(self, code, instructions, start, marker, end, stack):
    r = orig_pvc(self, code, instructions, start, marker, end, stack)
    print("PARSE_VALUE_CHAIN start=%s marker=%s end=%s -> %s" % (start, marker, end, None if r is None else (len(r[0]), r[1])))
    return r
Base._parse_value_chain = traced
orig_mcc = Base._match_compare_chain
def traced2(self, code, instructions, idx, marker, end, stack):
    r = orig_mcc(self, code, instructions, idx, marker, end, stack)
    print("MATCH_COMPARE_CHAIN idx=%s marker=%s end=%s -> %s" % (idx, marker, end, None if r is None else r[1]))
    return r
Base._match_compare_chain = traced2
dec = Base(); dec.dis = ForceDis(tl)
print(dec.decompile(fn))
