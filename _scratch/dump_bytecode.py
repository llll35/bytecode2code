"""Debug script to dump bytecode for failing probe cases."""
import ast
import dis
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyvers import compile_source, decompile
import tempfile

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

D3_TWO = (
    "def f(x):\n"
    "    try:\n"
    "        try:\n"
    "            return 1\n"
    "        finally:\n"
    "            x = 1\n"
    "    finally:\n"
    "        x = 2\n"
)

D3_FINALLY_WITH_EXCEPT = (
    "def f(x):\n"
    "    try:\n"
    "        try:\n"
    "            raise ValueError(x)\n"
    "        except ValueError as e:\n"
    "            return e\n"
    "    finally:\n"
    "        x = 1\n"
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
    "d3_two_levels": D3_TWO,
    "d3_finally_with_except": D3_FINALLY_WITH_EXCEPT,
    "d4_else_in_loop": D4_ELSE_LOOP,
    "d4_else_with_break": D4_ELSE_BREAK,
}

version = sys.argv[1] if len(sys.argv) > 1 else "3.9"
tmp = tempfile.mkdtemp()

for name, source in CASES.items():
    pyc = os.path.join(tmp, f"{name}_{version}.pyc")
    compile_source(source, pyc, version=version, dfile="<probe>")
    print(f"\n{'='*60}")
    print(f"CASE: {name} (Python {version})")
    print(f"{'='*60}")
    print("ORIGINAL:")
    print(source)
    print("\nBYTECODE:")
    try:
        co = compile(source, "<test>", "exec")
        for const in co.co_consts:
            if hasattr(const, 'co_code'):
                print(f"\n--- code: {const.co_name} ---")
                dis.dis(const)
    except Exception as e:
        print(f"Error: {e}")
