import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.decompiler import Decompiler
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser

tmp = tempfile.mkdtemp()
for label, src in {
    "assign": "def f(a, b, c, d, e):\n    r = a < b < c < d < e\n    return r\n",
    "not": "def f(a, b, c, d, e):\n    return not (a < b < c < d < e)\n",
    "mixed": "def f(a, b, c, d, e):\n    return a < b <= c != d is e\n",
}.items():
    p = os.path.join(tmp, label + ".pyc")
    compile_source_to_pyc(src, p)
    fn = [c for c in PyCParser.parse_file(p).code.co_consts if hasattr(c, "co_code")][0]
    d = Decompiler()
    ins = d.dis.disassemble(fn)
    print("===", label)
    for i, x in enumerate(ins):
        print("%3d %4d %-24s %s" % (i, x.offset, x.opname, repr(x.argval)))
    marker = d._find_chain_marker(ins, 0, len(ins))
    print("  marker:", marker)
    print("  match_compare_chain:", d._match_compare_chain(fn, ins, 0, marker, len(ins)))
    print("  value_chain consumed:", d._try_emit_value_chain(fn, ins, 0, len(ins), []))
    print("  boolop consumed:", d._try_emit_boolop(fn, ins, 0, len(ins), [], []))
    print()