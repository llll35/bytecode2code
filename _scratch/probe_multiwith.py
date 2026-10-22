import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyvers import compile_source, decompile

CASES = {
    "multi_with": "def f(a, b):\n    with a as x, b as y:\n        return x + y\n",
    "multi_with2": "def f(a, b):\n    with a as x, b as y:\n        z = x + y\n    return z\n",
    "multi_with3": "def f(a, b, c):\n    with a as x, b as y, c as z:\n        return x\n",
    "single_with": "def f(a):\n    with a as x:\n        return x\n",
    "nested_with": "def f(a, b):\n    with a as x:\n        with b as y:\n            return x + y\n",
}
tmp = tempfile.mkdtemp()
for v in ("3.9", "3.10", "3.11", "3.12"):
    print("=== %s ===" % v)
    for n, s in CASES.items():
        p = os.path.join(tmp, "%s_%s.pyc" % (n, v))
        try:
            compile_source(s, p, version=v, dfile="<p>")
            out = decompile(p).get("source", "")
            print("--- %s ---" % n)
            print(out, end="")
        except Exception as exc:
            print("--- %s --- ERROR %s: %s" % (n, type(exc).__name__, exc))
    print()