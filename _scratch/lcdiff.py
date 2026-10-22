import sys, os, marshal, py_compile, tempfile, dis
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers.decomp311 import Rewriter
src = "def h(a, b, c, d, e):\n    r = a < b <= c != d is e\n    return r, not (a < b < c < d < e)\n"
outs = {}
for ver in ("3.9","3.12"):
    d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
    pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
    with open(pyc,"rb") as fh:
        fh.read(16); code = marshal.loads(fh.read())
    fn = [c for c in code.co_consts if hasattr(c,"co_code")][0]
    outs[ver] = Rewriter(fn).run()
a, b = outs["3.9"], outs["3.12"]
print("len39=%d len312=%d" % (len(a), len(b)))
for x, y in zip(a, b):
    mark = "  " if (x.opname==y.opname and x.argval==y.argval) else "**"
    print("%s39[%4d %-22s jt=%-5s line=%s]  312[%4d %-22s jt=%-5s line=%s]" % (
        mark, x.offset, x.opname, x.is_jump_target, x.line_no,
        y.offset, y.opname, y.is_jump_target, y.line_no))
