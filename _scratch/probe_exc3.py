import sys, os, tempfile, ast
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.decompiler import Decompiler
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser

tmp = tempfile.mkdtemp()
p = os.path.join(tmp, "as_else.pyc")
compile_source_to_pyc(
    "def f(n):\n"
    "    try:\n"
    "        x = int(n)\n"
    "    except ValueError as e:\n"
    "        print(e)\n"
    "    else:\n"
    "        return x\n", p)
fn = [c for c in PyCParser.parse_file(p).code.co_consts if hasattr(c, "co_code")][0]

d = Decompiler()
ins = d.dis.disassemble(fn)
handler_start = 7
try_end = d._find_pop_block(ins, 0, 14)
print("try_end_idx:", try_end, ins[try_end].opname)
parsed = d._parse_except_handlers(fn, ins, handler_start, try_end)
print("parsed is None:", parsed is None)
if parsed:
    handlers, orelse, post = parsed
    print("handlers:", ast.dump(ast.Module(body=[ast.Try(body=[ast.Pass()], handlers=handlers, orelse=orelse)], type_ignores=[]))[:400])
    print("orelse:", [type(s).__name__ for s in orelse], "post:", post)
    if not orelse:
        print("recover:", [type(s).__name__ for s in d._recover_else_clause(fn, ins, try_end, handler_start, post)])
print("final:", d.decompile(PyCParser.parse_file(p).code))