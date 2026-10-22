"""Verify the try/finally + return fix.

Test cases from tests/cases.py "retfinally" probe plus additional edge cases.
Compiles source with py_compile, decompiles with stock Decompiler, and checks
semantic equivalence by exec'ing both original and decompiled source.
"""
import ast, os, py_compile, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser


CASES = {
    # From tests/cases.py "retfinally" probe
    "ret_simple": (
        "def a():\n"
        "    try:\n"
        "        return 1\n"
        "    finally:\n"
        "        x = 1\n"
    ),
    "ret_val": (
        "def b():\n"
        "    try:\n"
        "        return 1\n"
        "    finally:\n"
        "        pass\n"
    ),
    "ret_expr": (
        "def c(n):\n"
        "    try:\n"
        "        return n + 1\n"
        "    finally:\n"
        "        y = n * 2\n"
        "    return y\n"
    ),
    # Additional: return inside conditional in try body
    "ret_in_if": (
        "def d(n):\n"
        "    try:\n"
        "        if n:\n"
        "            return 1\n"
        "    finally:\n"
        "        pass\n"
        "    return 0\n"
    ),
    # Nested try/finally with return
    "ret_nested": (
        "def e(x):\n"
        "    try:\n"
        "        try:\n"
        "            return 1\n"
        "        finally:\n"
        "            x = 1\n"
        "    finally:\n"
        "        x = 2\n"
    ),
    # Edge case: return in try body inside a loop (the problematic one)
    "ret_break": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            return x\n"
        "        finally:\n"
        "            pass\n"
        "    return 0\n"
    ),
}


def run_one(name, source):
    """Return (status, output, detail)."""
    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, f"{name}.py")
        pyc_path = os.path.join(tmp, f"{name}.pyc")
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(source)
        py_compile.compile(src_path, cfile=pyc_path, doraise=True)

        pyc_file = PyCParser.parse_file(pyc_path)
        dec = Decompiler()
        result = dec.decompile(pyc_file.code)

        # Syntax check
        try:
            compile(result, f"{name}_out.py", "exec")
        except SyntaxError as e:
            return ("SYNTAX_ERROR", result, str(e))

        # Semantic check: exec both and call
        g_orig, g_result = {}, {}
        exec(compile(source, f"{name}_orig.py", "exec"), g_orig)
        exec(compile(result, f"{name}_result.py", "exec"), g_result)

        # Determine how to call each function
        tree = ast.parse(source)
        func_name = tree.body[0].name
        func_def = tree.body[0]

        args = []
        defaults = func_def.args.defaults
        # For simplicity: try with no args first, then with sample args
        arg_names = [a.arg for a in func_def.args.args]
        kwonly = [a.arg for a in func_def.args.kwonlyargs]

        test_calls = {}
        if "xs" in arg_names:
            test_calls[func_name] = [([1, 2, 3],), ([],), ([42],)]
        elif "n" in arg_names:
            test_calls[func_name] = [(0,), (5,), (True,), (False,)]
        elif "x" in arg_names:
            test_calls[func_name] = [(0,)]
        else:
            test_calls[func_name] = [()]

        mismatches = []
        for fname, calls in test_calls.items():
            if fname not in g_orig or fname not in g_result:
                mismatches.append(f"function {fname!r} not found")
                continue
            for call_args in calls:
                try:
                    r1 = g_orig[fname](*call_args)
                    r2 = g_result[fname](*call_args)
                    if r1 != r2:
                        mismatches.append(
                            f"{fname}{call_args}: orig={r1!r}, result={r2!r}"
                        )
                except Exception as e:
                    mismatches.append(
                        f"{fname}{call_args}: orig raised {type(e).__name__}: {e}"
                    )

        if mismatches:
            return ("MISMATCH", result, "; ".join(mismatches[:3]))
        return ("OK", result, "")


def main():
    print(f"Python {sys.version_info.major}.{sys.version_info.minor}")
    print("=" * 70)

    all_ok = True
    for name, source in CASES.items():
        status, result, detail = run_one(name, source)
        mark = "PASS" if status == "OK" else "FAIL"
        if status != "OK":
            all_ok = False
        print(f"\n[{mark}] {name}")
        print(f"  Source:\n{source.strip()}")
        print(f"  Output:\n{result}")
        if detail:
            print(f"  Detail: {detail}")

    print("\n" + "=" * 70)
    print("ALL PASSED" if all_ok else "SOME TESTS FAILED")
    print("=" * 70)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
