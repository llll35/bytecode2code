import sys, os, tempfile, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser

tmp = tempfile.mkdtemp()
CASES = {
    "wb": "def f(n):\n"
          "    while True:\n"
          "        try:\n"
          "            if n:\n"
          "                break\n"
          "        finally:\n"
          "            n -= 1\n"
          "    return n\n",
    "wb2": "def f(n):\n"
           "    while True:\n"
           "        try:\n"
           "            break\n"
           "        finally:\n"
           "            n -= 1\n"
           "    return n\n",
    "wb3": "def f(n):\n"
           "    while True:\n"
           "        try:\n"
           "            if n:\n"
           "                break\n"
           "        finally:\n"
           "            n = n\n"
           "    return n\n",
    "forwb": "def f(xs):\n"
             "    for x in xs:\n"
             "        try:\n"
             "            break\n"
             "        finally:\n"
             "            x = 0\n"
             "    return 1\n",
}
print("running on", sys.version_info[:2])
for name, src in CASES.items():
    p = os.path.join(tmp, name + ".pyc")
    compile_source_to_pyc(src, p)
    print("=== %s" % name)
    try:
        print("  " + Decompiler().decompile(PyCParser.parse_file(p).code)
              .replace("\n", "\n  "))
    except Exception:
        traceback.print_exc()
    print()