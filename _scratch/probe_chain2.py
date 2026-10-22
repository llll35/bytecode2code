import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bytecode2code.decompiler import Decompiler
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser
from tests.equivalence import compare

CASES = {
    "c2": "def f(a, b):\n    return a < b\n",
    "c3": "def f(a, b, c):\n    return a < b < c\n",
    "c4": "def f(a, b, c, d):\n    return a < b < c < d\n",
    "c5": "def f(a, b, c, d, e):\n    return a < b < c < d < e\n",
    "c6": "def f(a, b, c, d, e, g):\n    return a < b < c < d < e < g\n",
    "c5_assign": "def f(a, b, c, d, e):\n    r = a < b < c < d < e\n    return r\n",
    "c5_not": "def f(a, b, c, d, e):\n    return not (a < b < c < d < e)\n",
    "c5_mixed": "def f(a, b, c, d, e):\n    return a < b <= c != d is e\n",
}

tmp = tempfile.mkdtemp()
bad = []
for name, src in CASES.items():
    p = os.path.join(tmp, name + ".pyc")
    compile_source_to_pyc(src, p)
    original = PyCParser.parse_file(p).code
    out = Decompiler().decompile(original)
    try:
        recompiled = compile(out, name + ".py", "exec")
    except SyntaxError as exc:
        print("=== %-10s SyntaxError: %s" % (name, exc))
        bad.append(name)
        continue
    diffs = compare(original, recompiled)
    print("=== %-10s %s" % (name, "identical" if not diffs else "DIFF: " + "; ".join(diffs[:2])))
    if diffs:
        bad.append(name)
        print("   " + out.replace("\n", "\n   "))
print("failing:", bad or "none")