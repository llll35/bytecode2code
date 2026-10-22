import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.decompiler import Decompiler
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser
from tests.equivalence import compare

CASES = {
    "h": "def h(a, b, c, d, e):\n    r = a < b <= c != d is e\n    return r, not (a < b < c < d < e)\n",
    "h1": "def h(a, b, c, d, e):\n    r = a < b <= c != d is e\n    return r\n",
    "h2": "def h(a, b, c, d, e):\n    return r, not (a < b < c < d < e)\n",
    "h3": "def h(a, b, c, d, e):\n    r = a < b < c < d < e\n    return r\n",
    "h4": "def h(a, b, c, d, e):\n    return not (a < b < c < d < e)\n",
    "h5": "def h(a, b, c, d, e):\n    return a < b <= c != d is e\n",
}
tmp = tempfile.mkdtemp()
for name, src in CASES.items():
    p = os.path.join(tmp, name + ".pyc")
    compile_source_to_pyc(src, p)
    original = PyCParser.parse_file(p).code
    out = Decompiler().decompile(original)
    try:
        d = compare(original, compile(out, name + ".py", "exec"))
    except SyntaxError as exc:
        print("=== %-4s SyntaxError %s" % (name, exc))
        continue
    print("=== %-4s %s" % (name, "identical" if not d else "DIFF: " + "; ".join(d[:2])))
    if d:
        print("   " + out.replace("\n", "\n   "))