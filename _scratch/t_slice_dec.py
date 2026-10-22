import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyvers.decomp_compat import make_decompiler
V = "%d.%d" % sys.version_info[:2]
SRC = (
    "def a(s, i, j):\n"
    "    return s[i:j]\n"
    "def b(s, i, j, k):\n"
    "    return s[i:j:k]\n"
    "def c(s, i, j, v):\n"
    "    s[i:j] = v\n"
    "def d(s, i):\n"
    "    return s[i:]\n"
    "def e(s, j):\n"
    "    return s[:j]\n"
    "def f(s, n):\n"
    "    return s[-n:] if len(s) > n else s\n"
)
print(make_decompiler(V).decompile(compile(SRC, "t.py", "exec")))
