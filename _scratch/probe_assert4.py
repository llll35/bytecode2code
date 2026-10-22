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
inner = d._process_instruction


def traced(instr, instructions, idx, code, stack, stmts, **kw):
    n = len(stack)
    r = inner(instr, instructions, idx, code, stack, stmts, **kw)
    print("   replay %-22s -> %s ; stack %d->%d %s"
          % (instr.opname, r, n, len(stack),
             [type(x).__name__ + ":" + ast_dump(x) for x in stack]))
    return r


def ast_dump(x):
    try:
        import ast as _a
        return _a.unparse(x)
    except Exception:
        return "?"


d._process_instruction = traced
print(d.decompile(PyCParser.parse_file(p).code))