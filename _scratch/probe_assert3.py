import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.decompiler import Decompiler
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser

print("running on", sys.version_info[:2])
tmp = tempfile.mkdtemp()
p = os.path.join(tmp, "const.pyc")
compile_source_to_pyc("def f(a):\n    assert a, 'boom'\n", p)
fn = [c for c in PyCParser.parse_file(p).code.co_consts if hasattr(c, "co_code")][0]

d = Decompiler()
ins = d.dis.disassemble(fn)
original = d._try_emit_assert


def traced(instr, instructions, idx, code, stack, stmts, limit=None):
    r = original(instr, instructions, idx, code, stack, stmts, limit)
    print("  _try_emit_assert(idx=%d %s) -> %s ; stack=%s stmts=%s"
          % (idx, instr.opname, r, [type(x).__name__ for x in stack],
             [type(x).__name__ for x in stmts]))
    return r


d._try_emit_assert = traced
print(d.decompile(PyCParser.parse_file(p).code))