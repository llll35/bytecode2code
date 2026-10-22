"""The four control-flow defects listed in bugs.md, checked on every version.

Each case is compiled by the embedded interpreter of the requested version and
decompiled back through pyvers, then the result is compared with the source at
AST level.

    .venv\\Scripts\\python.exe -B _scratch\\probe_controlflow.py [3.9 3.10 ...]
"""
import ast
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pyvers import compile_source, decompile, interp

# D1: module level try/except swallowing the definitions that follow it.
D1 = {
    "d1_then_class": (
        "try:\n"
        "    import json\n"
        "except ImportError:\n"
        "    json = None\n"
        "class Later:\n"
        "    x = 1\n"
    ),
    "d1_then_func": (
        "try:\n"
        "    import json\n"
        "except ImportError:\n"
        "    json = None\n"
        "def later():\n"
        "    return 1\n"
    ),
    "d1_then_import": (
        "try:\n"
        "    import json\n"
        "except ImportError:\n"
        "    json = None\n"
        "import os\n"
    ),
    "d1_two_classes": (
        "try:\n"
        "    import json\n"
        "except ImportError:\n"
        "    json = None\n"
        "class A:\n"
        "    pass\n"
        "class B:\n"
        "    pass\n"
    ),
}

# D2: break/continue inside a try block.
D2 = {
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
    "d2_break_after_try": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            y = x\n"
        "        except ValueError:\n"
        "            pass\n"
        "        if x:\n"
        "            break\n"
        "    return 1\n"
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
    "d2_continue_in_except": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            y = int(x)\n"
        "        except ValueError:\n"
        "            continue\n"
        "    return 1\n"
    ),
}

# D3: nested finally blocks.
D3 = {
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
}

# D4: the else clause boundary around a try block.
D4 = {
    "d4_else": (
        "def f(x):\n"
        "    try:\n"
        "        a = x\n"
        "    except ValueError:\n"
        "        a = 1\n"
        "    else:\n"
        "        a = 2\n"
        "    return a\n"
    ),
    "d4_else_then_code": (
        "def f(x):\n"
        "    try:\n"
        "        a = x\n"
        "    except ValueError:\n"
        "        a = 1\n"
        "    else:\n"
        "        a = 2\n"
        "    b = a + 1\n"
        "    return b\n"
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
    "d4_else_with_break": (
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
    ),
}

GROUPS = {"D1": D1, "D2": D2, "D3": D3, "D4": D4}
VERSIONS = sys.argv[1:] or ["3.9", "3.10", "3.11", "3.12"]


def normalise(tree):
    for node in ast.walk(tree):
        if hasattr(node, "lineno"):
            node.lineno = 0
            node.col_offset = 0
    return ast.dump(tree)


def main():
    tmp = tempfile.mkdtemp()
    failures = 0
    for version in VERSIONS:
        if interp.interpreter_path(version) is None:
            print("skip %s (no interpreter)" % version)
            continue
        print("=== Python %s ===" % version)
        for group in sorted(GROUPS):
            for name in sorted(GROUPS[group]):
                source = GROUPS[group][name]
                pyc = os.path.join(tmp, "%s_%s.pyc" % (name, version))
                try:
                    compile_source(source, pyc, version=version, dfile="<probe>")
                    out = decompile(pyc).get("source", "")
                except Exception as exc:
                    print("  %-22s ERROR %s: %s" % (name, type(exc).__name__, exc))
                    failures += 1
                    continue
                try:
                    got = ast.parse(out)
                except SyntaxError as exc:
                    print("  %-22s SYNTAX line %s: %s"
                          % (name, exc.lineno, exc.msg))
                    print("      " + out.replace("\n", "\n      "))
                    failures += 1
                    continue
                if normalise(ast.parse(source)) == normalise(got):
                    print("  %-22s ok" % name)
                else:
                    print("  %-22s AST DIFF" % name)
                    print("      " + out.replace("\n", "\n      "))
                    failures += 1
    print("\n%d failing" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())