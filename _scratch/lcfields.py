import sys, dataclasses
sys.path.insert(0, r"D:\py\bytecode2code")
a = None; b = None
import json, os, marshal, py_compile, tempfile
from bytecode2code import Disassembler
from pyvers.decomp311 import Rewriter

src = "def h(a, b, c, d, e):\n    r = a < b <= c != d is e\n    return r, not (a < b < c < d < e)\n"

def compile_code(ver):
    d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
    pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
    with open(pyc,"rb") as fh:
        fh.read(16); code = marshal.loads(fh.read())
    return [c for c in code.co_consts if hasattr(c,"co_code")][0]

a = Disassembler().disassemble(compile_code("3.9"))
b = Rewriter(compile_code("3.12")).run()
print("fields:", [f for f in dir(a[0]) if not f.startswith("_") and not callable(getattr(a[0], f))])
for i,(x,y) in enumerate(zip(a,b)):
    if x.__dict__ != y.__dict__:
        print("DIFF at", i)
        for k in x.__dict__:
            if x.__dict__[k] != y.__dict__.get(k):
                print("   %s: 39=%r 312=%r" % (k, x.__dict__[k], y.__dict__.get(k)))
