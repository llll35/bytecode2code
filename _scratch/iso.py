import os, sys, tempfile
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers import compile_source, decompile

CASES = {
  "delete": "def f(a):\n    del a[0]\n    del a.b\n    del a\n    return a\n",
  "longchain_h": "def h(a, b, c, d, e):\n    r = a < b <= c != d is e\n    return r, not (a < b < c < d < e)\n",
  "relative_star": "from os import path as p\nfrom os.path import *\n",
  "rel_import1": "from . import x\n",
  "rel_import4": "from os import path as p\n",
}
with tempfile.TemporaryDirectory() as d:
    for name, src in CASES.items():
        print("######## %s ########" % name)
        for version in ("3.9","3.11","3.12"):
            pyc = os.path.join(d, "x_%s_%s.pyc" % (version, name))
            compile_source(src, pyc, version=version)
            print("--- %s ---" % version)
            print(decompile(pyc)["source"])
