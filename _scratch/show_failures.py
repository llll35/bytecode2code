"""Decompile the remaining selftest failure sources and show output."""
import os
import sys
import py_compile
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser

CASES = {
    "finally_print": "def f(p):\n    try:\n        g()\n    finally:\n        print(p)\n",
    "nested_try": (
        "def f(p):\n    try:\n        try:\n            g()\n"
        "        finally:\n            h()\n    except ValueError:\n        pass\n"
    ),
    "try_loop": (
        "def f(p):\n    for i in p:\n        try:\n            g(i)\n"
        "        finally:\n            h()\n"
    ),
    "try_loop_continue": (
        "def f(p):\n    for i in p:\n        try:\n            g(i)\n"
        "        finally:\n            h()\n        continue\n"
    ),
    "with_try": (
        "def f(p):\n    try:\n        with open(p) as fh:\n"
        "            g(fh)\n        if not None:\n            raise\n"
        "    except ValueError:\n        pass\n"
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
    print("=" * 50)
    print(name)
    print("-- source --")
    print(src, end="")
    print("-- output --")
    print(Decompiler().decompile(code))
