import dis, marshal, py_compile, tempfile, os, re
# find every opname used across a broad corpus compiled with 3.12
samples = {
 "tuple_build": "def f(a,b):\n    t = (a,b)\n    return t\n",
 "comps": "def f(n):\n    return [x for x in range(n)]\n",
 "with": "def f(p):\n    with open(p) as fh:\n        pass\n",
 "match": "def f(x):\n    match x:\n        case 0:\n            return 'z'\n        case _:\n            return 'o'\n",
 "trystar": "def f():\n    try:\n        pass\n    except* ValueError:\n        pass\n",
}
ops = set()
for tag, src in samples.items():
    d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
    pyc = os.path.join(d,"s.pyc")
    try: py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
    except Exception as e: print(tag, "fail", e); continue
    with open(pyc,"rb") as fh:
        fh.read(16); code = marshal.loads(fh.read())
    stack=[code]
    while stack:
        c = stack.pop()
        for ins in dis.get_instructions(c):
            ops.add(ins.opname)
        stack.extend(x for x in c.co_consts if hasattr(x,"co_code"))
print("3.12 ops:", sorted(ops))
