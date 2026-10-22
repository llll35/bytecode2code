import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.decompiler import Decompiler
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser

src = "def f(a, b, c, d):\n    return a < b < c < d\n"
tmp = tempfile.mkdtemp()
p = os.path.join(tmp, "c4.pyc")
compile_source_to_pyc(src, p)
code = PyCParser.parse_file(p).code
fn = [c for c in code.co_consts if hasattr(c, "co_code")][0]

d = Decompiler()
ins = d.dis.disassemble(fn)
for i, x in enumerate(ins):
    print("%3d %4d %-24s %s" % (i, x.offset, x.opname, repr(x.argval)))

print("marker            :", d._find_chain_marker(ins, 0, len(ins)))
print("value chain parse :", d._parse_value_chain(ins and code, ins, 0, d._find_chain_marker(ins, 0, len(ins)), len(ins), []) and "OK" or None)
r = d._parse_value_chain(code, ins, 0, d._find_chain_marker(ins, 0, len(ins)), len(ins), [])
print("full result       :", r)
print("eval 6..9         :", d._eval_ifexp_expr(code, ins, 6, 9, [d._eval_ifexp_expr(code, ins, 0, 2, [])[-1]]))