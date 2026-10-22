import sys, os, marshal, py_compile, tempfile, dis
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers.decomp311 import Rewriter, _exception_entries
src = "def f(p):\n    try:\n        g()\n    finally:\n        print(p)\n"
d = tempfile.mkdtemp()
p = os.path.join(d, "s.py")
open(p,"w").write(src)
pyc = os.path.join(d,"s.pyc")
py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
with open(pyc,"rb") as fh:
    fh.read(16); code = marshal.loads(fh.read())
fn = [c for c in code.co_consts if hasattr(c,"co_code") and c.co_name=="f"][0]
rw = Rewriter(fn)
print("drops:", sorted(hex(o) for o in rw._drops))
print("try_setups:", {hex(k):[hex(t) for t in v] for k,v in rw.try_setups.items()})
print("try_closes:", {hex(k):hex(v) for k,v in rw.try_closes.items()})
print("try_before:", {hex(k):v for k,v in rw.try_before.items()})
print("try_replace:", {hex(k):v for k,v in rw.try_replace.items()})
print("retarget:", {hex(k):hex(v) for k,v in rw._retarget.items()})
print("tail_offsets:", sorted(hex(o) for o in getattr(rw,"_tail_offsets",set())))
print("tails_at_merge:", {hex(k):[hex(r.offset) for r in v] for k,v in getattr(rw,"_tails_at_merge",{}).items()})
out = rw.run()
print("=== TRANSLATED (3.9 shape) ===")
for ins in out:
    print("  offset=%4d %-22s arg=%s argval=%s line=%s" % (ins.offset, ins.opname, ins.arg, ins.argval, ins.line_no))
