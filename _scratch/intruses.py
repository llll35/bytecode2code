import dis, marshal, py_compile, tempfile, os
samples = {
 "unary_plus": "def f(a):\n    return +a\n",
 "tuple_lit": "def f(a):\n    return (a, a)\n",
 "import_star": "from os.path import *\n",
 "asyncgen": "async def f():\n    yield 1\n",
 "print_stmt": "print(1)\n",
}
for tag, src in samples.items():
    d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
    pyc = os.path.join(d,"s.pyc")
    try:
        py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
    except Exception as e:
        print(tag, "compile fail", e); continue
    with open(pyc,"rb") as fh:
        fh.read(16); code = marshal.loads(fh.read())
    print("=== 3.12 %s ===" % tag)
    dis.dis(code)
