import sys, os, tempfile, dis, ast
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser

tmp = tempfile.mkdtemp()
src = ("def c(n):\n"
       "    try:\n"
       "        return n + 1\n"
       "    finally:\n"
       "        y = n * 2\n"
       "    return y\n")
p = os.path.join(tmp, "c.pyc")
compile_source_to_pyc(src, p)
code = PyCParser.parse_file(p).code
fn = [c for c in code.co_consts if hasattr(c, "co_code") and c.co_name == "c"][0]
for i in dis.get_instructions(fn):
    mark = " >>" if i.is_jump_target else "   "
    print("%4d %s %-22s %s" % (i.offset, mark, i.opname, repr(i.argval)))
print("--- decompiled ---")
print(Decompiler().decompile(code))