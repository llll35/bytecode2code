"""Debug script to analyze bytecode for failing probe cases."""
import ast
import dis
import sys
import tempfile
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyvers import compile_source, decompile

D2_BREAK = (
    "def f(xs):\n"
    "    for x in xs:\n"
    "        try:\n"
    "            if x:\n"
    "                break\n"
    "        finally:\n"
    "            x = 0\n"
    "    return x\n"
)

D2_CONTINUE = (
    "def f(xs):\n"
    "    for x in xs:\n"
    "        try:\n"
    "            if not x:\n"
    "                continue\n"
    "        finally:\n"
    "            x = 1\n"
    "    return x\n"
)

D3_NESTED = (
    "def f(x):\n"
    "    try:\n"
    "        try:\n"
    "            try:\n"
    "                return 1\n"
    "            finally:\n"
    "                x = 1\n"
    "        finally:\n"
    "            x = 2\n"
    "    finally:\n"
    "        x = 3\n"
)

D4_ELSE_LOOP = (
    "def f(xs):\n"
    "    for x in xs:\n"
    "        try:\n"
    "            a = x\n"
    "        except ValueError:\n"
    "            a = 1\n"
    "        else:\n"
    "            a = 2\n"
    "    return a\n"
)

D4_ELSE_BREAK = (
    "def f(xs):\n"
    "    for x in xs:\n"
    "        try:\n"
    "            if x:\n"
    "                break\n"
    "        except ValueError:\n"
    "            pass\n"
    "        else:\n"
    "            x = 1\n"
    "    return x\n"
)

CASES = {
    "d2_try_break": D2_BREAK,
    "d2_try_continue": D2_CONTINUE,
    "d3_nested_finally": D3_NESTED,
    "d4_else_in_loop": D4_ELSE_LOOP,
    "d4_else_with_break": D4_ELSE_BREAK,
}

tmp = tempfile.mkdtemp()
version = sys.argv[1] if len(sys.argv) > 1 else "3.9"

for name, source in CASES.items():
    pyc = os.path.join(tmp, f"{name}_{version}.pyc")
    compile_source(source, pyc, version=version, dfile="<probe>")
    out = decompile(pyc).get("source", "")
    print(f"\n{'='*60}")
    print(f"CASE: {name} (Python {version})")
    print(f"{'='*60}")
    print("ORIGINAL:")
    print(source)
    print("\nDECOMPILED:")
    print(out)
    try:
        orig_ast = ast.dump(ast.parse(source))
        got_ast = ast.dump(ast.parse(out))
        print("\nMATCH:", orig_ast == got_ast)
    except SyntaxError as e:
        print(f"\nSYNTAX ERROR: {e}")
