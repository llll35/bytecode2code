import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.decompiler import Decompiler
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser
from tests.equivalence import compare

print("running on", sys.version_info[:2])
tmp = tempfile.mkdtemp()
CASES = {
    "bare": "def f(a):\n    assert a\n",
    "const": "def f(a):\n    assert a, 'boom'\n",
    "call": "def f(a, E):\n    assert a.x, E('why')\n",
    "plain_call": "def f(a, E):\n    b = E('why')\n    assert a, b\n",
}
for name, src in CASES.items():
    p = os.path.join(tmp, name + ".pyc")
    compile_source_to_pyc(src, p)
    original = PyCParser.parse_file(p).code
    fn = [c for c in original.co_consts if hasattr(c, "co_code")][0]
    d = Decompiler()
    ins = d.dis.disassemble(fn)
    print("=== %s" % name)
    for i, x in enumerate(ins):
        print("   %2d %4d %-22s %s" % (i, x.offset, x.opname, repr(x.argval)))
    out = d.decompile(original)
    print("   ->", out.replace("\n", "\n      "))
    try:
        diffs = compare(original, compile(out, name + ".py", "exec"))
        print("   ", "identical" if not diffs else "DIFF: " + "; ".join(diffs[:2]))
    except SyntaxError as exc:
        print("   SyntaxError", exc)
    print()