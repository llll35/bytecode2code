"""Baseline behaviour of with variants on 3.9."""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser
import py_compile
import tempfile

CASES = {
    "single_return": "def f(a):\n    with a as x:\n        return x\n",
    "single_if_return": (
        "def f(a, c):\n"
        "    with a as x:\n"
        "        if c:\n"
        "            return x\n"
        "        y = 1\n"
        "    return y\n"
    ),
    "multi_return": "def f(a, b):\n    with a as x, b as y:\n        return x + y\n",
    "multi_body": "def f(a, b):\n    with a as x, b as y:\n        z = x + y\n    return z\n",
    "multi_break": (
        "def f(a, b):\n"
        "    for i in a:\n"
        "        with a as x, b as y:\n"
        "            break\n"
    ),
    "single_break": (
        "def f(a):\n"
        "    for i in a:\n"
        "        with a as x:\n"
        "            break\n"
    ),
    "single_continue": (
        "def f(a):\n"
        "    for i in a:\n"
        "        with a as x:\n"
        "            continue\n"
    ),
    "nested_with_return": (
        "def f(a, b):\n"
        "    with a as x:\n"
        "        with b as y:\n"
        "            return x + y\n"
    ),
}

tmp = tempfile.mkdtemp()
for name, src in CASES.items():
    p = os.path.join(tmp, name + ".py")
    pyc = os.path.join(tmp, name + ".pyc")
    with open(p, "w") as f:
        f.write(src)
    py_compile.compile(p, cfile=pyc, doraise=True)
    code = PyCParser.parse_file(pyc).code
    out = Decompiler().decompile(code)
    print("=" * 60)
    print(name)
    print("-- source --")
    print(src, end="")
    print("-- output --")
    print(out)
