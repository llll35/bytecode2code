import sys, os, marshal, py_compile, tempfile
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers.decomp311 import Rewriter, Decompiler311
from pyvers.decomp_compat import Decompiler310
src = "def h(a, b, c, d, e):\n    r = a < b <= c != d is e\n    return r, not (a < b < c < d < e)\n"
d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
with open(pyc,"rb") as fh:
    fh.read(16); code = marshal.loads(fh.read())
fn = [c for c in code.co_consts if hasattr(c,"co_code")][0]
print("=== via Decompiler311 ===")
print(Decompiler311().decompile(fn))
print("=== via Decompiler310 (raw 3.12 code, not translated) ===")
try:
    print(Decompiler310().decompile(fn))
except Exception as e:
    print("ERR", e)
