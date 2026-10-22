import sys, os, tempfile
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
pro = d._parse_exception_prologue(ins, 7, len(ins))
print("prologue:", [type(x).__name__ for x in pro], pro[1], "body_start=", pro[3],
      "as_target=", pro[4], "as_idx=", pro[5])
body, post = d._parse_handler_body(fn, ins, pro[3], pro[4], pro[5],
                                  d._find_target_idx(ins, pro[1 + 2]))
print("body:", [type(s).__name__ for s in body], "post:", post)
print("find_pop_block(13, 48):", d._find_pop_block(ins, 13, 48))
print("find_target_idx(48):", d._find_target_idx(ins, 48))