import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.decompiler import Decompiler
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser

tmp = tempfile.mkdtemp()
for label, src in {
    "loop_try_noas": (
        "def main():\n"
        "    while True:\n"
        "        try:\n"
        "            break\n"
        "        except ValueError:\n"
        "            print(1)\n"
        "    results = []\n"
        "    return results\n"
    ),
    "plain_try": (
        "def main():\n"
        "    try:\n"
        "        x = 1\n"
        "    except ValueError:\n"
        "        print(1)\n"
        "    results = []\n"
        "    return results\n"
    ),
}.items():
    p = os.path.join(tmp, label + ".pyc")
    compile_source_to_pyc(src, p)
    fn = [c for c in PyCParser.parse_file(p).code.co_consts if hasattr(c, "co_code")][0]
    d = Decompiler()
    ins = d.dis.disassemble(fn)
    print("===", label)
    for i, x in enumerate(ins):
        tgt = "  ; target=%d" % x.offset if False else ""
        print("%3d %4d %-24s %s" % (i, x.offset, x.opname, repr(x.argval)))
    print()