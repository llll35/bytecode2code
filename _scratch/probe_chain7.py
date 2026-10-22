import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code import decompiler as dc
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser

tmp = tempfile.mkdtemp()
p = os.path.join(tmp, "h2.pyc")
compile_source_to_pyc("def h(a, b, c, d, e):\n    return r, not (a < b < c < d < e)\n", p)
fn = [c for c in PyCParser.parse_file(p).code.co_consts if hasattr(c, "co_code")][0]

d = dc.Decompiler()
ins = d.dis.disassemble(fn)
stack, stmts = [], []
for name in ("_try_emit_chain_cond", "_try_emit_boolop", "_try_emit_value_chain",
             "_try_emit_value_boolop"):
    got = getattr(d, name)
    if name == "_try_emit_chain_cond":
        r = got(fn, ins, 0, len(ins), stack, stmts)
    elif name == "_try_emit_boolop":
        r = got(fn, ins, 0, len(ins), stack, stmts)
    elif name == "_try_emit_value_chain":
        r = got(fn, ins, 0, len(ins), stack)
    else:
        r = got(fn, ins, 0, len(ins), stack)
    print("%-26s -> %s   stack=%s stmts=%s" % (
        name, r, [type(x).__name__ for x in stack], [type(x).__name__ for x in stmts]))