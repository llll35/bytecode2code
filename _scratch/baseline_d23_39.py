"""Baseline behaviour of D2/D3 try/finally cases on 3.9."""
import ast
import os
import sys
import py_compile
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser

CASES = {
    "d3_two_levels": (
        "def f(x):\n"
        "    try:\n"
        "        try:\n"
        "            return 1\n"
        "        finally:\n"
        "            x = 1\n"
        "    finally:\n"
        "        x = 2\n"
    ),
    "d3_nested_finally": (
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
    ),
    "d3_finally_with_except": (
        "def f(x):\n"
        "    try:\n"
        "        try:\n"
        "            raise ValueError(x)\n"
        "        except ValueError as e:\n"
        "            return e\n"
        "    finally:\n"
        "        x = 1\n"
    ),
    "d2_try_break": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            if x:\n"
        "                break\n"
        "        finally:\n"
        "            x = 0\n"
        "    return x\n"
    ),
    "d2_try_continue": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            if not x:\n"
        "                continue\n"
        "        finally:\n"
        "            x = 1\n"
        "    return x\n"
    ),
    "d2_while_break_finally": (
        "def f(n):\n"
        "    while True:\n"
        "        try:\n"
        "            if n:\n"
        "                break\n"
        "        finally:\n"
        "            n -= 1\n"
        "    return n\n"
    ),
    "d4_else_in_loop": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            a = x\n"
        "        except ValueError:\n"
        "            a = 1\n"
        "        else:\n"
        "            a = 2\n"
        "    return a\n"
    ),
}

tmp = tempfile.mkdtemp()
for name, src in CASES.items():
    p = os.path.join(tmp, name + ".py")
    c = os.path.join(tmp, name + ".pyc")
    with open(p, "w") as f:
        f.write(src)
    py_compile.compile(p, cfile=c, doraise=True)
    code = PyCParser.parse_file(c).code
    out = Decompiler().decompile(code)
    print("=" * 60)
    print(name)
    print("-- output --")
    print(out)
