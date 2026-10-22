import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.decompiler import Decompiler
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser

tmp = tempfile.mkdtemp()
for label, src in {
    "h2": "def h(a, b, c, d, e):\n    return r, not (a < b < c < d < e)\n",
    "h4": "def h(a, b, c, d, e):\n    return not (a < b < c < d < e)\n",
}.items():
    p = os.path.join(tmp, label + ".pyc")
    compile_source_to_pyc(src, p)
    fn = [c for c in PyCParser.parse_file(p).code.co_consts if hasattr(c, "co_code")][0]
    d = Decompiler()
    ins = d.dis.disassemble(fn)
    print("===", label)
    for i, x in enumerate(ins):
        print("%3d %4d %-24s %s" % (i, x.offset, x.opname, repr(x.argval)))
    for i in range(len(ins)):
        m = d._find_chain_marker(ins, i, len(ins)) or d._find_value_chain_marker(ins, i, len(ins))
        if m is not None:
            print("   from %d marker=%s match=%s" % (
                i, m, d._match_compare_chain(fn, ins, i, m, len(ins), [])[1]
                if d._match_compare_chain(fn, ins, i, m, len(ins), []) else None))
            break
    print()