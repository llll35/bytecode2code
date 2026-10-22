"""Deep inspection of the ret_break edge case on Python 3.9 bytecode."""

import ast
import dis
import os
import py_compile
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser


SOURCE = """\
def f(xs):
    for x in xs:
        try:
            return x
        finally:
            pass
    return 0
"""

with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "test.py")
    pyc_path = os.path.join(tmp, "test.pyc")
    with open(src_path, "w", encoding="utf-8") as f:
        f.write(SOURCE)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)

    pyc_file = PyCParser.parse_file(pyc_path)
    print("=== Original bytecode ===")
    for co in pyc_file.code.co_consts:
        if hasattr(co, "co_name") and co.co_name == "f":
            dis.dis(co)
            print()

    dec = Decompiler()
    result = dec.decompile(pyc_file.code)
    print("=== Decompiled output ===")
    print(result)

    # Check semantic equivalence
    g_orig = {}
    g_decomp = {}
    exec(compile(SOURCE, "orig.py", "exec"), g_orig)
    exec(compile(result, "decomp.py", "exec"), g_decomp)

    orig_fn = g_orig["f"]
    decomp_fn = g_decomp["f"]

    for xs in ([1, 2, 3], [], [42]):
        r1 = orig_fn(xs)
        r2 = decomp_fn(xs)
        status = "OK" if r1 == r2 else f"MISMATCH: orig={r1}, decomp={r2}"
        print(f"f({xs}) = {r1} vs {r2}  -> {status}")

    # Also check AST structure
    tree_orig = ast.parse(SOURCE)
    tree_decomp = ast.parse(result)
    orig_body = tree_orig.body[0].body
    decomp_body = tree_decomp.body[0].body
    print("\n=== AST comparison ===")
    print(f"Original try body: {[ast.dump(s) for s in orig_body[0].body]}")
    print(f"Decompiled try body: {[ast.dump(s) for s in decomp_body[0].body]}")
