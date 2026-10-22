import sys, dis, marshal, py_compile, tempfile, os
src = "def f(p):\n    try:\n        g()\n    finally:\n        print(p)\n"
d = tempfile.mkdtemp()
p = os.path.join(d, "s.py")
open(p, "w").write(src)
pyc = os.path.join(d, "s.pyc")
py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
with open(pyc, "rb") as fh:
    fh.read(16)
    code = marshal.loads(fh.read())
fn = [c for c in code.co_consts if hasattr(c, "co_code") and c.co_name == "f"][0]
print("=== NATIVE 3.12 ===")
dis.dis(fn)
print("=== exception table ===")
for e in dis._parse_exception_table(fn):
    print(e)
