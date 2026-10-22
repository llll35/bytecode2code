import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pyvers.decomp_compat import make_decompiler

V = "%d.%d" % sys.version_info[:2]
SRC = (
    "def a(d, x):\n"
    "    d.append(str(x))\n"
    "def b(d, x):\n"
    "    while x:\n"
    "        d.append(str(x))\n"
    "        x -= 1\n"
    "def c(d, x):\n"
    "    d.append(x)\n"
)
print(make_decompiler(V).decompile(compile(SRC, "t.py", "exec")))
print("-" * 40)
import dis
code = compile(SRC, "t.py", "exec")
for const in code.co_consts:
    if hasattr(const, "co_name"):
        print("###", const.co_name)
        dis.dis(const)
