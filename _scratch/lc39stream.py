import sys, os, marshal, py_compile, tempfile
sys.path.insert(0, r"D:\py\bytecode2code")
from bytecode2code import Disassembler
from pyvers.decomp_compat import Decompiler310
src = "def h(a, b, c, d, e):\n    r = a < b <= c != d is e\n    return r, not (a < b < c < d < e)\n"
d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
with open(pyc,"rb") as fh:
    fh.read(16); code = marshal.loads(fh.read())
fn = [c for c in code.co_consts if hasattr(c,"co_code")][0]
native = Disassembler().disassemble(fn)
print("=== NATIVE 3.9 instruction stream ===")
for i in native:
    print("  %4d %-24s arg=%s argval=%s jt=%s" % (i.offset, i.opname, i.arg, i.argval, i.is_jump_target))
