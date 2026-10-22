import os, marshal, py_compile, tempfile, dis
for ver, exe in (("3.9", r"D:\py\bytecode2code\embed_python\python-3.9\python.exe"),
                 ("3.11", r"D:\py\bytecode2code\embed_python\python-3.11\python.exe")):
    pass
src = "def f(p):\n    try:\n        g()\n    except ValueError:\n        pass\n    else:\n        h()\n    print(1)\n"
d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
with open(pyc,"rb") as fh:
    fh.read(16); code = marshal.loads(fh.read())
fn = [c for c in code.co_consts if hasattr(c,"co_code") and c.co_name=="f"][0]
print("=== NATIVE 3.9 (else) ===")
dis.dis(fn)
