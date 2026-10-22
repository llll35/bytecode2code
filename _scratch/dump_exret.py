import sys, os, marshal, py_compile, tempfile, dis
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers.decomp311 import Rewriter
src = "def f(p):\n    try:\n        return int(p)\n    except ValueError:\n        return 0\n"
d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
with open(pyc,"rb") as fh:
    fh.read(16); code = marshal.loads(fh.read())
fn = [c for c in code.co_consts if hasattr(c,"co_code") and c.co_name=="f"][0]
print("=== NATIVE 3.11 (except return) ===")
dis.dis(fn)
rw = Rewriter(fn)
print("drops:", sorted(hex(o) for o in rw._drops))
print("try_closes:", {hex(k):hex(v) for k,v in rw.try_closes.items()})
print("close_merges:", {hex(k):hex(v) for k,v in rw._close_merge_offsets().items()})
print("try_replace keys:", [hex(k) for k in rw.try_replace])
print("=== TRANSLATED ===")
for ins in rw.run():
    print("  %4d %-22s arg=%s argval=%s" % (ins.offset, ins.opname, ins.arg, ins.argval))
