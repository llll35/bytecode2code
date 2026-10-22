"""Show the fake-3.9 stream the 3.11/3.12 rewriter produces for a snippet.

usage: python _scratch\rw.py <version> < file.py
"""
import os
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

version = sys.argv[1]
source = sys.stdin.read()

folder = tempfile.mkdtemp()
py = os.path.join(folder, "s.py")
with open(py, "w", encoding="utf-8") as fh:
    fh.write(source)
pyc = os.path.join(folder, "s.pyc")
subprocess.run(
    [os.path.join(_ROOT, "embed_python", "python-%s" % version, "python.exe"),
     "-c",
     "import py_compile,sys; py_compile.compile(sys.argv[1], cfile=sys.argv[2], "
     "dfile='<s>', doraise=True)", py, pyc],
    check=True,
)

script = r'''
import sys, marshal
sys.path.insert(0, r"@@ROOT@@")
from pyvers.decomp311 import Rewriter
with open(sys.argv[1], "rb") as fh:
    fh.read(16)
    code = marshal.loads(fh.read())
for const in code.co_consts:
    if hasattr(const, "co_code"):
        rw = Rewriter(const)
        out = rw.run()
        print("=== TRANSLATED (3.9 shape) for %s ===" % getattr(const, "co_name", "<module>"))
        for ins in out:
            print("  offset=%4d %-22s arg=%s argval=%s" % (ins.offset, ins.opname, ins.arg, ins.argval))
'''.replace("@@ROOT@@", _ROOT)

probe = os.path.join(folder, "probe.py")
with open(probe, "w", encoding="utf-8") as fh:
    fh.write(script)
out = subprocess.run(
    [os.path.join(_ROOT, "embed_python", "python-%s" % version, "python.exe"),
     probe, pyc],
    capture_output=True, text=True,
)
sys.stdout.write(out.stdout)
sys.stderr.write(out.stderr)
