import sys, os, tempfile, ast
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser

CASES = {
    "ret_simple": "def f():\n    try:\n        return 1\n    finally:\n        x = 1\n",
    "ret_val": "def f():\n    try:\n        return 1\n    finally:\n        pass\n",
    "ret_in_if": "def f(n):\n    try:\n        if n:\n            return 1\n    finally:\n        pass\n    return 0\n",
    "ret_nested": "def f(x):\n    try:\n        try:\n            return 1\n        finally:\n            x = 1\n    finally:\n        x = 2\n",
    "ret_break": "def f(xs):\n    for x in xs:\n        try:\n            return x\n        finally:\n            pass\n    return 0\n",
}
tmp = tempfile.mkdtemp()
for name, src in CASES.items():
    p = os.path.join(tmp, name + ".pyc")
    compile_source_to_pyc(src, p)
    original = PyCParser.parse_file(p).code
    out = Decompiler().decompile(original)
    print("=== %s" % name)
    print(out, end="")
    try:
        got = ast.parse(out)
        same = ast.dump(ast.parse(src)) == ast.dump(got)
        print("   [%s]" % ("identical" if same else "AST DIFF"))
    except SyntaxError as e:
        print("   [SyntaxError %s]" % e)
    print()