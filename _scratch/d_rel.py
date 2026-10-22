import dis, marshal, py_compile, tempfile, os
src = "from os import path as p\nfrom os.path import *\n"
d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
with open(pyc,"rb") as fh:
    fh.read(16); code = marshal.loads(fh.read())
print("=== NATIVE 3.12 relative_star ===")
dis.dis(code)
