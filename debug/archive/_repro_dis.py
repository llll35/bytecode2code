import os, sys, tempfile, dis
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers import compile_source, dispatch
from pyvers.decomp311 import Rewriter, _exception_entries

src = "def f(p):\n    try:\n        g()\n    finally:\n        print(p)\n"

with tempfile.TemporaryDirectory() as d:
    pyc = os.path.join(d, "a.pyc")
    compile_source(src, pyc, version="3.11")
    info = dispatch.call_pyc(pyc, "code_info")
    # get the nested code object raw via worker
    data = dispatch.call_pyc(pyc, "dump_ir")
    print("=== native dis 3.11 for f ===")
