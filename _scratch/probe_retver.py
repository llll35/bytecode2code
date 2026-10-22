import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyvers import compile_source, decompile

CASES = {
    "ret_simple": "def f():\n    try:\n        return 1\n    finally:\n        x = 1\n",
    "ret_val": "def f():\n    try:\n        return 1\n    finally:\n        pass\n",
    "ret_stack": "def c(n):\n    try:\n        return n + 1\n    finally:\n        y = n * 2\n    return y\n",
    "ret_only": "def f():\n    try:\n        return 1\n    finally:\n        x = 1\n    return 2\n",
}
tmp = tempfile.mkdtemp()
for v in ("3.9", "3.10", "3.11", "3.12"):
    print("=== %s ===" % v)
    for name, src in CASES.items():
        p = os.path.join(tmp, "%s_%s.pyc" % (name, v))
        compile_source(src, p, version=v, dfile="<p>")
        out = decompile(p).get("source", "")
        print("--- %s ---" % name)
        print(out, end="")
    print()