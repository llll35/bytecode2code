import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyvers import compile_source, decompile, interp
from tests.cases import PROBES

for version in ("3.9", "3.11", "3.12"):
    tmp = tempfile.mkdtemp()
    src = PROBES["chainedassign"]
    pyc = os.path.join(tmp, "ca.pyc")
    compile_source(src, pyc, version=version, dfile="<p>")
    print("=== %s ===" % version)
    print(decompile(pyc).get("source", ""))

# what does the 3.12 decompiler actually see?
from pyvers import dispatch
tmp = tempfile.mkdtemp()
pyc = os.path.join(tmp, "m.pyc")
compile_source("a = b = 1\n", pyc, version="3.12", dfile="<p>")
print("=== 3.12 module disassembly ===")
print(dispatch.disassemble(pyc)["text"])