import dis, marshal, py_compile, tempfile, os
src = "def f(a,b,c,d):\n    return a < b < c < d\n"
d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
with open(pyc,"rb") as fh:
    fh.read(16); code = marshal.loads(fh.read())
fn = [c for c in code.co_consts if hasattr(c,"co_code")][0]
print("=== 3.12 chain_return ==="); dis.dis(fn)
