"""Sweep a batch of source constructs across every supported version.

Each case is compiled and decompiled with the embedded interpreter of that
version and the result is compared with the source's own AST.

usage: python _scratch\sweep.py [version ...]
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
    "with as in loop": (
        "def f(paths):\n"
        "    out = []\n"
        "    for p in paths:\n"
        "        with open(p) as fh:\n"
        "            out.append(fh.read())\n"
        "    return out\n"
    ),
    "with two managers": (
        "def f(a, b):\n"
        "    with open(a) as x, open(b) as y:\n"
        "        return x.read() + y.read()\n"
    ),
    "nested with in try": (
        "def f(a, b):\n"
        "    try:\n"
        "        with open(a) as x:\n"
        "            with open(b) as y:\n"
        "                return x.read() + y.read()\n"
        "    except OSError:\n"
        "        return ''\n"
    ),
    "try in loop": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            g(x)\n"
        "        except ValueError:\n"
        "            continue\n"
        "    return 1\n"
    ),
    "except tuple": (
        "def f(p):\n"
        "    try:\n"
        "        g(p)\n"
        "    except (ValueError, TypeError) as e:\n"
        "        return e\n"
    ),
    "except reraise": (
        "def f(p):\n"
        "    try:\n"
        "        g(p)\n"
        "    except ValueError:\n"
        "        raise\n"
    ),
    "nested try in except": (
        "def f(p):\n"
        "    try:\n"
        "        g(p)\n"
        "    except ValueError:\n"
        "        try:\n"
        "            h(p)\n"
        "        except TypeError:\n"
        "            pass\n"
    ),
    "finally with return": (
        "def f(p):\n"
        "    try:\n"
        "        return g(p)\n"
        "    finally:\n"
        "        h(p)\n"
    ),
    "while else": (
        "def f(xs):\n"
        "    while xs:\n"
        "        xs.pop()\n"
        "    else:\n"
        "        return 1\n"
    ),
    "for else": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        g(x)\n"
        "    else:\n"
        "        return 1\n"
    ),
    "class with try": (
        "class C:\n"
        "    def __init__(self, p):\n"
        "        try:\n"
        "            self.v = int(p)\n"
        "        except ValueError:\n"
        "            self.v = 0\n"
    ),
    "generator with try": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            yield x\n"
        "        except ValueError:\n"
        "            continue\n"
    ),
    "comprehension in try": (
        "def f(p):\n"
        "    try:\n"
        "        return [int(x) for x in p]\n"
        "    except ValueError:\n"
        "        return []\n"
    ),
    "lambda in try": (
        "def f(p):\n"
        "    try:\n"
        "        cb = lambda x: int(x)\n"
        "    except ValueError:\n"
        "        cb = None\n"
        "    return cb\n"
    ),
    "nested function in try": (
        "def f(p):\n"
        "    try:\n"
        "        def g(x):\n"
        "            return int(x)\n"
        "    except ValueError:\n"
        "        g = None\n"
        "    return g\n"
    ),
    "with in while": (
        "def f(p):\n"
        "    while True:\n"
        "        with open(p) as fh:\n"
        "            if fh.read():\n"
        "                break\n"
        "    return 1\n"
    ),
    "try except in with": (
        "def f(p):\n"
        "    with open(p) as fh:\n"
        "        try:\n"
        "            return fh.read()\n"
        "        except OSError:\n"
        "            return ''\n"
    ),
    "assert in try": (
        "def f(p):\n"
        "    try:\n"
        "        assert p\n"
        "    except AssertionError:\n"
        "        return 0\n"
    ),
    "del in try": (
        "def f(p):\n"
        "    x = p\n"
        "    try:\n"
        "        del x\n"
        "    except NameError:\n"
        "        pass\n"
    ),
    "global in try": (
        "x = 0\n"
        "def f(p):\n"
        "    global x\n"
        "    try:\n"
        "        x = p\n"
        "    except ValueError:\n"
        "        x = 0\n"
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
                    print("  %-24s CRASH %s: %s" % (name, type(exc).__name__, exc))
                    continue
            try:
                got_ast = ast.dump(ast.parse(got))
            except SyntaxError as exc:
                print("  %-24s SYNTAX line %s: %s" % (name, exc.lineno, exc.msg))
                print("    " + got.replace("\n", "\n    "))
                continue
            want = ast.dump(ast.parse(source))
            if got_ast == want:
                print("  %-24s ok" % name)
            else:
                print("  %-24s DIFF" % name)
                print("    " + got.replace("\n", "\n    "))
                if os.environ.get("SWEEP_DUMP"):
                    import difflib
                    left = ast.dump(ast.parse(source), indent=1).splitlines()
                    right = ast.dump(ast.parse(got), indent=1).splitlines()
                    for line in list(difflib.unified_diff(
                            left, right, "source", "got", lineterm=""))[:40]:
                        print("    | " + line)


if __name__ == "__main__":
    main()
