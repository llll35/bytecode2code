import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pyvers.decomp_compat import make_decompiler

V = "%d.%d" % sys.version_info[:2]
SRC = (
    "def first[T](xs: list[T]) -> T:\n"
    "    return xs[0]\n"
    "class Box[T]:\n"
    "    pass\n"
    "type Alias = int\n"
)
out = make_decompiler(V).decompile(compile(SRC, "t.py", "exec"))
print(out)
print("-" * 40)
import ast
try:
    ast.parse(out)
    print("parses")
except SyntaxError as exc:
    print("SyntaxError line", exc.lineno, exc.msg)
