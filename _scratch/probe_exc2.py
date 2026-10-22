import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.decompiler import Decompiler
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser

tmp = tempfile.mkdtemp()
for label, src in {
    "as_ret": "def f(n):\n    try:\n        x = int(n)\n    except ValueError as e:\n        return 1\n    return None\n",
    "as_else": "def f(n):\n    try:\n        x = int(n)\n    except ValueError as e:\n        print(e)\n    else:\n        return x\n",
}.items():
    p = os.path.join(tmp, label + ".pyc")
    compile_source_to_pyc(src, p)
    fn = [c for c in PyCParser.parse_file(p).code.co_consts if hasattr(c, "co_code")][0]
    d = Decompiler()
    ins = d.dis.disassemble(fn)
    print("===", label)
    for i, x in enumerate(ins):
        print("%3d %4d %-24s %s" % (i, x.offset, x.opname, repr(x.argval)))
    print("  ---- decompiled ----")
    print("  " + d.decompile(PyCParser.parse_file(p).code).replace("\n", "\n  "))
    print()