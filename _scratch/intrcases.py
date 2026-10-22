import os, sys, tempfile
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers import compile_source, decompile
CASES = {
 "unary_plus": "def f(a):\n    return +a\n",
 "import_star": "from os.path import *\n",
 "asyncgen": "async def f():\n    yield 1\n",
}
with tempfile.TemporaryDirectory() as d:
    for name, src in CASES.items():
        print("######## %s ########" % name)
        for version in ("3.9","3.11","3.12"):
            pyc = os.path.join(d, "i_%s_%s.pyc" % (version, name))
            compile_source(src, pyc, version=version)
            print("--- %s ---" % version); print(decompile(pyc)["source"])
