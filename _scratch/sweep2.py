"""Second sweep: constructs outside the exception/with area.

usage: python _scratch\sweep2.py [version ...]
"""
import ast
import os
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from pyvers import dispatch  # noqa: E402

CASES = {
    "class with methods": (
        "class C:\n"
        "    x = 1\n"
        "    def m(self, a, b=2, *c, d=3, **e):\n"
        "        return (a, b, c, d, e)\n"
        "    @property\n"
        "    def p(self):\n"
        "        return self.x\n"
    ),
    "class with try in init": (
        "class C:\n"
        "    def __init__(self, p):\n"
        "        try:\n"
        "            self.v = int(p)\n"
        "        except ValueError as e:\n"
        "            self.v = 0\n"
        "            self.err = e\n"
    ),
    "nested class": (
        "class Outer:\n"
        "    class Inner:\n"
        "        def m(self):\n"
        "            return 1\n"
    ),
    "closure": (
        "def outer(n):\n"
        "    def inner(x):\n"
        "        return x + n\n"
        "    return inner\n"
    ),
    "comprehension conditions": (
        "def f(xs):\n"
        "    return [x * 2 for x in xs if x > 1]\n"
    ),
    "nested comprehension": (
        "def f(xs):\n"
        "    return [y for x in xs for y in x]\n"
    ),
    "dict comprehension": (
        "def f(xs):\n"
        "    return {x: x * 2 for x in xs}\n"
    ),
    "generator expression": (
        "def f(xs):\n"
        "    return sum(x for x in xs)\n"
    ),
    "fstring formats": (
        "def f(x):\n"
        "    return f'{x!r:>10} and {x:=#x} and {x}'\n"
    ),
    "walrus": (
        "def f(xs):\n"
        "    if (n := len(xs)) > 1:\n"
        "        return n\n"
        "    return 0\n"
    ),
    "conditional expression": (
        "def f(x):\n"
        "    return 1 if x else 2\n"
    ),
    "chained comparison": (
        "def f(x):\n"
        "    return 0 < x < 10\n"
    ),
    "boolean operators": (
        "def f(x, y):\n"
        "    return x and y or not x\n"
    ),
    "augmented assign": (
        "def f(xs):\n"
        "    n = 0\n"
        "    for x in xs:\n"
        "        n += x\n"
        "        n **= 2\n"
        "    return n\n"
    ),
    "tuple unpacking": (
        "def f(p):\n"
        "    a, b, *c = p\n"
        "    return (a, b, c)\n"
    ),
    "star args": (
        "def f(*a, **k):\n"
        "    return a, k\n"
    ),
    "nested function with closure over loop": (
        "def f(xs):\n"
        "    out = []\n"
        "    for x in xs:\n"
        "        def g():\n"
        "            return x\n"
        "        out.append(g)\n"
        "    return out\n"
    ),
    "raise from": (
        "def f(p):\n"
        "    try:\n"
        "        g(p)\n"
        "    except ValueError as e:\n"
        "        raise TypeError('x') from e\n"
    ),
    "assert with message": (
        "def f(p):\n"
        "    assert p, 'must be set'\n"
        "    return p\n"
    ),
    "multiple assignment": (
        "def f(p):\n"
        "    a = b = p\n"
        "    c, d = p, p\n"
        "    return a, b, c, d\n"
    ),
    "global nonlocal": (
        "g = 0\n"
        "def outer():\n"
        "    h = 0\n"
        "    def inner():\n"
        "        global g\n"
        "        nonlocal h\n"
        "        g = 1\n"
        "        h = 2\n"
        "    inner()\n"
    ),
    "slicing": (
        "def f(s):\n"
        "    return s[1:2], s[::2], s[::-1], s[a:b:c]\n"
    ),
    "subscript assign": (
        "def f(d, k):\n"
        "    d[k] = 1\n"
        "    d[k] += 1\n"
        "    return d\n"
    ),
    "attribute assign": (
        "def f(o):\n"
        "    o.x = 1\n"
        "    o.x += 1\n"
        "    return o.x\n"
    ),
    "del forms": (
        "def f(d, xs):\n"
        "    del d['k']\n"
        "    del xs[0]\n"
        "    return d\n"
    ),
    "import forms": (
        "import os\n"
        "import os.path\n"
        "from os import path\n"
        "from os import path as p\n"
        "from . import sibling\n"
    ),
    "try in method with self": (
        "class C:\n"
        "    def m(self, p):\n"
        "        try:\n"
        "            return self.n(p)\n"
        "        except ValueError:\n"
        "            return None\n"
        "    def n(self, p):\n"
        "        return int(p)\n"
    ),
    "while with break and else": (
        "def f(xs):\n"
        "    while xs:\n"
        "        x = xs.pop()\n"
        "        if x:\n"
        "            break\n"
        "    else:\n"
        "        return 1\n"
        "    return 2\n"
    ),
    "nested while in for": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        while x:\n"
        "            x -= 1\n"
        "    return 1\n"
    ),
    "try in for with break": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            g(x)\n"
        "            break\n"
        "        except ValueError:\n"
        "            pass\n"
        "    return 1\n"
    ),
}


def main():
    versions = sys.argv[1:] or ["3.9", "3.10", "3.11", "3.12"]
    for version in versions:
        print("=" * 70)
        print("VERSION", version)
        for name in sorted(CASES):
            source = CASES[name]
            with tempfile.TemporaryDirectory() as folder:
                pyc = os.path.join(folder, "case.pyc")
                try:
                    dispatch.compile_source(source, pyc, version=version,
                                            dfile="<probe>")
                    got = dispatch.decompile(pyc)["source"]
                except Exception as exc:  # noqa: BLE001
                    print("  %-28s CRASH %s: %s" % (name, type(exc).__name__, exc))
                    continue
            try:
                got_ast = ast.dump(ast.parse(got))
            except SyntaxError as exc:
                print("  %-28s SYNTAX line %s: %s" % (name, exc.lineno, exc.msg))
                print("    " + got.replace("\n", "\n    "))
                continue
            want = ast.dump(ast.parse(source))
            if got_ast == want:
                print("  %-28s ok" % name)
            else:
                print("  %-28s DIFF" % name)
                print("    " + got.replace("\n", "\n    "))


if __name__ == "__main__":
    main()
