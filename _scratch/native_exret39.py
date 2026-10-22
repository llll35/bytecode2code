import os, marshal, py_compile, tempfile, dis
src = "def f(p):\n    try:\n        return int(p)\n    except ValueError:\n        return 0\n"
d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
with open(pyc,"rb") as fh:
    fh.read(16); code = marshal.loads(fh.read())
fn = [c for c in code.co_consts if hasattr(c,"co_code") and c.co_name=="f"][0]
print("=== NATIVE 3.9 (except return) ===")
dis.dis(fn)
