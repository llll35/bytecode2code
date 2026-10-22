"""Debug multiwith: with a as x, b as y: return x + y"""
import ast, dis, os, py_compile, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser

SRC = "def f(a, b):\n    with a as x, b as y:\n        return x + y\n"

with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "test.py")
    pyc_path = os.path.join(tmp, "test.pyc")
    with open(src_path, "w") as f:
        f.write(SRC)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)

    pyc_file = PyCParser.parse_file(pyc_path)
    print("=== NATIVE DIS ===")
    dis.dis(pyc_file.code)

    # nested code object for f
    for c in pyc_file.code.co_consts:
        if hasattr(c, "co_code"):
            print("=== CODE OBJECT:", c.co_name, "===")
            print("=== DISASSEMBLY ===")
            dis.dis(c)

    dec = Decompiler()
    out = dec.decompile(pyc_file.code)
    print("=== OUTPUT ===")
    print(out)
