import sys, os, tempfile, ast
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser
from pyvers import compile_source, decompile

SRC = ("def f(x):\n"
       "    try:\n"
       "        try:\n"
       "            pass\n"
       "        finally:\n"
       "            x = 1\n"
       "    finally:\n"
       "        x = 2\n"
       "    return 1\n")

tmp = tempfile.mkdtemp()
p1 = os.path.join(tmp, "a.pyc")
compile_source_to_pyc(SRC, p1)
direct = Decompiler().decompile(PyCParser.parse_file(p1).code)
print("=== direct (3.9) ===")
print(direct)

p2 = os.path.join(tmp, "b.pyc")
compile_source(SRC, p2, version="3.9", dfile="<probe>")
via = decompile(p2).get("source", "")
print("=== pyvers (3.9) ===")
print(via)
print("=== equal:", direct == via)
print("=== AST equal:", ast.dump(ast.parse(direct)) == ast.dump(ast.parse(via)))