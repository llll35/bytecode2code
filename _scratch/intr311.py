import dis, marshal, py_compile, tempfile, os
for tag, src in {"unary_plus":"def f(a):\n    return +a\n","import_star":"from os.path import *\n","asyncgen":"async def f():\n    yield 1\n"}.items():
    d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
    pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
    with open(pyc,"rb") as fh:
        fh.read(16); code = marshal.loads(fh.read())
    print("=== 3.11 %s ===" % tag)
    dis.dis(code)
