import sys, os, tempfile, dis
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser

tmp = tempfile.mkdtemp()
src = ("def f(x):\n"
       "    try:\n"
       "        try:\n"
       "            pass\n"
       "        finally:\n"
       "            x = 1\n"
       "    finally:\n"
       "        x = 2\n"
       "    return 1\n")
p = os.path.join(tmp, "d3.pyc")
compile_source_to_pyc(src, p)
fn = [c for c in PyCParser.parse_file(p).code.co_consts if hasattr(c, "co_code")][0]
kw = {"show_caches": False} if sys.version_info >= (3, 11) else {}
for i in dis.get_instructions(fn, **kw):
    mark = " >>" if i.is_jump_target else "   "
    print("%4d %s %-22s %s" % (i.offset, mark, i.opname, repr(i.argval)))