"""Verify ret_nested and try_except_return separately."""
import ast, os, py_compile, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser


# --- ret_nested: check semantic equivalence properly ---
src_nested = (
    "def e(x):\n"
    "    try:\n"
    "        try:\n"
    "            return 1\n"
    "        finally:\n"
    "            x = 1\n"
    "    finally:\n"
    "        x = 2\n"
)

with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "e.py")
    pyc_path = os.path.join(tmp, "e.pyc")
    with open(src_path, "w") as f: f.write(src_nested)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)
    pyc_file = PyCParser.parse_file(pyc_path)
    dec = Decompiler()
    result = dec.decompile(pyc_file.code)
    print("=== ret_nested output ===")
    print(result)

    g_o, g_r = {}, {}
    exec(compile(src_nested, "o.py", "exec"), g_o)
    exec(compile(result, "r.py", "exec"), g_r)
    for x in (0, 99):
        r1 = g_o["e"](x)
        r2 = g_r["e"](x)
        print(f"e({x}): orig={r1}, decomp={r2}, match={r1==r2}")


# --- try_except_return: check if pre-existing ---
src_tryex = (
    "def n():\n"
    "    try:\n"
    "        return 5\n"
    "    except ValueError:\n"
    "        return 6\n"
)

with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "n.py")
    pyc_path = os.path.join(tmp, "n.pyc")
    with open(src_path, "w") as f: f.write(src_tryex)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)
    pyc_file = PyCParser.parse_file(pyc_path)
    dec = Decompiler()
    result = dec.decompile(pyc_file.code)
    print("\n=== try_except_return output ===")
    print(result)

    g_o, g_r = {}, {}
    exec(compile(src_tryex, "o.py", "exec"), g_o)
    exec(compile(result, "r.py", "exec"), g_r)
    try:
        r1 = g_o["n"]()
        r2 = g_r["n"]()
        print(f"n(): orig={r1}, decomp={r2}, match={r1==r2}")
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
