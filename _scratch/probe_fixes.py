"""Round-trip probe: the fixes applied so far.

Run with the interpreter that matches the compiled ``.pyc``:

    embed_python\\python-3.9\\python.exe -B _scratch\\probe_fixes.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bytecode2code.decompiler import Decompiler
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser
from tests.equivalence import compare

CASES = {
    # del
    "del_sub": "def f(a):\n    del a[0]\n",
    "del_attr": "def f(a):\n    del a.b\n",
    # assert
    "assert": "def f(a):\n    assert a, 'x'\n",
    "assert_bare": "def f(a):\n    assert a\n",
    "assert_call": "def f(a):\n    assert a.x, E('y')\n",
    # class with keywords
    "cls_kw": "class C(dict, metaclass=type):\n    pass\n",
    "cls_kw2": "class D(Base, metaclass=Meta, extra=1):\n    x = 1\n",
    # chained assignment vs walrus
    "assign2": "a = b = 1\n",
    "assign3": "a = b = c = 1\n",
    "walrus_if": "def f(x):\n    if (y := x) > 1:\n        return y\n",
    "walrus_stmt": "def f(x):\n    (y := x)\n",
    "walrus_call": "def f(g):\n    return (n := g()) + 1\n",
    # starred unpacking
    "unpack_ex1": "def f(a):\n    *a, b = [1,2,3]\n",
    "unpack_ex2": "def f(a):\n    b, *a = [1,2,3]\n",
    "unpack_ex3": "def f(a):\n    b, *a, c = [1,2,3]\n",
    "unpack_ex4": "def f(a):\n    *a, = [1,2,3]\n",
    # relative imports
    "imp_dot": "from . import x\n",
    "imp_dot1": "from .mod import y\n",
    "imp_dot2": "from ..pkg.mod import y as z\n",
    "imp_alias": "from os import path as p\n",
    "imp_plain": "import os\nfrom os import path as p\n",
    "imp_star": "from os.path import *\n",
    # state isolation across code objects
    "state_leak": "import sys\ndef inner():\n    import json\n    import re\n    return sys.path\n",
}


def main():
    tmp = tempfile.mkdtemp()
    failures = []
    for name, src in CASES.items():
        pyc = os.path.join(tmp, name + ".pyc")
        compile_source_to_pyc(src, pyc)
        original = PyCParser.parse_file(pyc).code
        print("=== %s ===" % name)
        try:
            out = Decompiler().decompile(original)
        except Exception as exc:
            print("  !! decompiler crashed: %s: %s" % (type(exc).__name__, exc))
            failures.append(name)
            print()
            continue
        print("  " + out.replace("\n", "\n  ").rstrip())
        try:
            recompiled = compile(out, name + ".py", "exec")
        except SyntaxError as exc:
            print("  !! output does not parse: %s" % exc)
            failures.append(name)
            print()
            continue
        diffs = compare(original, recompiled)
        if diffs:
            failures.append(name)
            print("  DIFF: " + "; ".join(diffs[:2]))
        else:
            print("  [round-trip identical]")
        print()

    print("%d/%d identical" % (len(CASES) - len(failures), len(CASES)))
    if failures:
        print("failing: %s" % ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())