import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.decompiler import Decompiler
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser
from tests.equivalence import compare

CASES = {
    "loop_try": (
        "def main():\n"
        "    while True:\n"
        "        n = input('x')\n"
        "        try:\n"
        "            parts = n.split(',')\n"
        "            break\n"
        "        except ValueError as e:\n"
        "            print(e)\n"
        "    results = []\n"
        "    return results\n"
    ),
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
        "    except ValueError as e:\n"
        "        print(e)\n"
        "    results = []\n"
        "    return results\n"
    ),
    "for_try": (
        "def main():\n"
        "    for i in range(3):\n"
        "        try:\n"
        "            x = i\n"
        "        except ValueError as e:\n"
        "            print(e)\n"
        "    results = []\n"
        "    return results\n"
    ),
}
tmp = tempfile.mkdtemp()
for name, src in CASES.items():
    p = os.path.join(tmp, name + ".pyc")
    compile_source_to_pyc(src, p)
    original = PyCParser.parse_file(p).code
    out = Decompiler().decompile(original)
    try:
        d = compare(original, compile(out, name + ".py", "exec"))
    except SyntaxError as exc:
        print("=== %-14s SyntaxError %s" % (name, exc))
        continue
    print("=== %-14s %s" % (name, "identical" if not d else "DIFF: " + "; ".join(d[:1])))
    if d:
        print("   " + out.replace("\n", "\n   "))