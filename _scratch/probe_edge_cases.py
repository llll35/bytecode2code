"""Probe various edge cases for try/finally + return."""
import ast, os, py_compile, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser


CASES = {
    # --- Existing retfinally probe cases ---
    "ret_simple": "def a():\n    try:\n        return 1\n    finally:\n        x = 1\n",
    "ret_val":    "def b():\n    try:\n        return 1\n    finally:\n        pass\n",
    "ret_expr":   "def c(n):\n    try:\n        return n + 1\n    finally:\n        y = n * 2\n    return y\n",
    "ret_in_if":  "def d(n):\n    try:\n        if n:\n            return 1\n    finally:\n        pass\n    return 0\n",
    "ret_nested": "def e(x):\n    try:\n        try:\n            return 1\n        finally:\n            x = 1\n    finally:\n        x = 2\n",
    "ret_break":  "def f(xs):\n    for x in xs:\n        try:\n            return x\n        finally:\n            pass\n    return 0\n",

    # --- Edge cases ---
    "ret_while": (
        "def g(flag):\n"
        "    while flag:\n"
        "        try:\n"
        "            return 42\n"
        "        finally:\n"
        "            pass\n"
        "    return 0\n"
    ),
    "ret_depth2": (  # two nested loops
        "def h(xs, ys):\n"
        "    for x in xs:\n"
        "        for y in ys:\n"
        "            try:\n"
        "                return (x, y)\n"
        "            finally:\n"
        "                pass\n"
        "    return 0\n"
    ),
    "ret_empty_try": (  # empty try body, return after finally
        "def i():\n"
        "    try:\n"
        "        pass\n"
        "    finally:\n"
        "        pass\n"
        "    return 7\n"
    ),
    "ret_with_expr": (  # return expression not just constant
        "def j(a, b):\n"
        "    try:\n"
        "        return a + b\n"
        "    finally:\n"
        "        pass\n"
    ),
    "ret_in_while_else": (  # return in try inside while with else
        "def k(n):\n"
        "    while n > 0:\n"
        "        try:\n"
        "            return n\n"
        "        finally:\n"
        "            n -= 1\n"
        "    return -1\n"
    ),
    "return_outside_try": (  # make sure normal returns still work
        "def m():\n"
        "    return 99\n"
    ),
    "try_except_return": (  # try/except, not try/finally
        "def n():\n"
        "    try:\n"
        "        return 5\n"
        "    except ValueError:\n"
        "        return 6\n"
    ),
}


def run_one(name, source):
    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, f"{name}.py")
        pyc_path = os.path.join(tmp, f"{name}.pyc")
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(source)
        py_compile.compile(src_path, cfile=pyc_path, doraise=True)

        pyc_file = PyCParser.parse_file(pyc_path)
        dec = Decompiler()
        result = dec.decompile(pyc_file.code)

        try:
            compile(result, f"{name}_out.py", "exec")
        except SyntaxError as e:
            return ("SYNTAX_ERROR", result, str(e))

        g_orig, g_result = {}, {}
        exec(compile(source, f"{name}_orig.py", "exec"), g_orig)
        exec(compile(result, f"{name}_result.py", "exec"), g_result)

        tree = ast.parse(source)
        func_name = tree.body[0].name
        fn = g_orig.get(func_name)
        rn = g_result.get(func_name)
        if fn is None or rn is None:
            return ("NOFUNC", result, f"{func_name} not found")

        arg_names = [a.arg for a in tree.body[0].args.args]
        mismatches = []
        # Generate test calls based on args
        if "flag" in arg_names:
            calls = [(True,), (False,)]
        elif "xs" in arg_names and "ys" in arg_names:
            calls = [([1,2], [3,4]), ([], [5]), ([6], [])]
        elif "a" in arg_names and "b" in arg_names:
            calls = [(10, 20), (0, 0), (-1, 1)]
        elif "n" in arg_names:
            calls = [(0,), (5,), (-3,)]
        elif "xs" in arg_names:
            calls = [([1,2,3],), ([],), ([42],)]
        else:
            calls = [()]

        for args in calls:
            try:
                r1 = fn(*args)
                r2 = rn(*args)
                if r1 != r2:
                    mismatches.append(f"{func_name}{args}: orig={r1!r}, decomp={r2!r}")
            except Exception as e:
                mismatches.append(f"{func_name}{args}: {type(e).__name__}: {e}")

        if mismatches:
            return ("MISMATCH", result, "; ".join(mismatches[:3]))
        return ("OK", result, "")


def main():
    print(f"Python {sys.version_info.major}.{sys.version_info.minor}")
    print("=" * 70)

    fails = []
    for name, source in CASES.items():
        status, result, detail = run_one(name, source)
        mark = "PASS" if status == "OK" else "FAIL"
        if status != "OK":
            fails.append(name)
        print(f"\n[{mark}] {name}")
        print(f"  Output:\n{result}")
        if detail:
            print(f"  Detail: {detail}")

    print("\n" + "=" * 70)
    if fails:
        print(f"FAILED ({len(fails)}): {', '.join(fails)}")
    else:
        print("ALL PASSED")
    print("=" * 70)
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
