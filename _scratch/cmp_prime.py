import ast, difflib, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.main import decompile_file
from bytecode2code.pyc_parser import PyCParser
from pyvers.decomp_compat import make_decompiler

pyc = os.path.join(ROOT, "tests", "samples", "prime.pyc")
src = open(os.path.join(ROOT, "tests", "samples", "prime.py"), encoding="utf-8").read()
base = decompile_file(pyc)
aware = make_decompiler("3.12").decompile(PyCParser.parse_file(pyc).code)

for label, out in (("BASE (decompile_file)", base), ("AWARE (decomp311)", aware)):
    print("=" * 30, label, "=" * 30)
    try:
        got = ast.unparse(ast.parse(out))
        want = ast.unparse(ast.parse(src))
        diff = list(difflib.unified_diff(want.splitlines(), got.splitlines(), "source", "out", lineterm="", n=1))
        print("differing lines:", len(diff))
        print("\n".join(diff[:40]))
    except SyntaxError as exc:
        print("DOES NOT PARSE:", exc)
        print(out[:600])
    print()
