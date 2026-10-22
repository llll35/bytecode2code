import sys, os, marshal, py_compile, tempfile, dis
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers.decomp311 import Rewriter
from pyvers.decomp_compat import Decompiler310
from pyvers.decomp311 import Decompiler311
src = "def f(a,b,c,d):\n    return a < b < c < d\n"
d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
with open(pyc,"rb") as fh:
    fh.read(16); code = marshal.loads(fh.read())
fn = [c for c in code.co_consts if hasattr(c,"co_code")][0]
rw = Rewriter(fn)
tl = rw.run()
for i in tl:
    print("  %4d %-24s arg=%s argval=%s jt=%s" % (i.offset, i.opname, i.arg, i.argval, i.is_jump_target))
print("---- decompiled ----")
print(Decompiler311().decompile(fn))
