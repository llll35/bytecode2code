import dis, marshal, py_compile, tempfile, os
samples = {
 "trystar": "def f():\n    try:\n        pass\n    except* ValueError as eg:\n        print(eg)\n",
 "match": "def f(x):\n    match x:\n        case 0:\n            return 'z'\n        case _:\n            return 'o'\n",
}
for tag, src in samples.items():
    d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
    pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
    with open(pyc,"rb") as fh:
        fh.read(16); code = marshal.loads(fh.read())
    fn = [c for c in code.co_consts if hasattr(c,"co_code")][0]
    print("=== 3.12 %s ===" % tag)
    dis.dis(fn)
