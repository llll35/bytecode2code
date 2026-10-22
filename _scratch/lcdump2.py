import sys, os, marshal, py_compile, tempfile, json
sys.path.insert(0, r"D:\py\bytecode2code")
from bytecode2code import Disassembler
from pyvers.decomp311 import Rewriter
src = "def h(a, b, c, d, e):\n    r = a < b <= c != d is e\n    return r, not (a < b < c < d < e)\n"
def compile_code(ver):
    d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
    pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
    with open(pyc,"rb") as fh:
        fh.read(16); code = marshal.loads(fh.read())
    return [c for c in code.co_consts if hasattr(c,"co_code")][0]
if sys.argv[1] == "39":
    a = Disassembler().disassemble(compile_code("3.9"))
else:
    a = Rewriter(compile_code("3.12")).run()
out = [dict(op=d.opname, arg=d.arg, argval=repr(d.argval), jt=d.is_jump_target, ln=d.line_no) for d in a]
with open(r"D:\py\bytecode2code\_scratch\lc_%s.json" % sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(out, fh)
