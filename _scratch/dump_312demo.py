import ast, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyvers.decomp_compat import make_decompiler
V = "%d.%d" % sys.version_info[:2]
path = os.path.join(ROOT, "tests", "samples", "py312_syntax_demo.py")
src = open(path, encoding="utf-8").read()
out = make_decompiler(V).decompile(compile(src, path, "exec"))
lines = out.splitlines()
print("total lines:", len(lines))
for i in range(30, 52):
    if i < len(lines):
        print("%4d| %s" % (i + 1, lines[i]))
