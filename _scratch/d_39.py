import dis, marshal, py_compile, tempfile, os
for src, tag in [("def f(a):\n    del a[0]\n    del a.b\n    del a\n    return a\n","delete"),
                 ("from os import path as p\nfrom os.path import *\n","rel")]:
    d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
    pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
    with open(pyc,"rb") as fh:
        fh.read(16); code = marshal.loads(fh.read())
    fn = code
    if tag == "delete":
        fn = [c for c in code.co_consts if hasattr(c,"co_code") and c.co_name=="f"][0]
    print("=== NATIVE 3.9 %s ===" % tag)
    dis.dis(fn)
