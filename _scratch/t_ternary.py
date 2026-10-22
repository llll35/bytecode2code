import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyvers.decomp_compat import make_decompiler

V = "%d.%d" % sys.version_info[:2]
SRC = (
    "def f(s, n):\n"
    "    return s[-n:] if len(s) > n else s\n"
    "def g(s, n):\n"
    "    t = s[-n:] if len(s) > n else s\n"
    "    return t\n"
)
code = compile(SRC, "t.py", "exec")
print(make_decompiler(V).decompile(code))
print("-" * 40)
import dis
for c in code.co_consts:
    if hasattr(c, "co_name") and c.co_name in ("f", "g"):
        print("###", c.co_name)
        dis.dis(c)
