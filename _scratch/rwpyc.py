"""Show the fake-3.9 stream the 3.11/3.12 rewriter produces for a .pyc module.

usage: python _scratch\rwpyc.py <version> <file.pyc> [codename]
"""
import os
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

version = sys.argv[1]
pyc = sys.argv[2]
want = sys.argv[3] if len(sys.argv) > 3 else None

script = r'''
import sys, marshal
sys.path.insert(0, r"@@ROOT@@")
from pyvers.decomp311 import Rewriter
with open(sys.argv[1], "rb") as fh:
    fh.read(16)
    code = marshal.loads(fh.read())
targets = [code] if sys.argv[2] in (None, "", "<module>") else [
    c for c in code.co_consts if hasattr(c, "co_code") and c.co_name == sys.argv[2]]
for const in targets:
    rw = Rewriter(const)
    out = rw.run()
    print("=== TRANSLATED (3.9 shape) for %s ===" % getattr(const, "co_name", "<module>"))
    for ins in out:
        print("  offset=%4d %-22s arg=%s argval=%s" % (ins.offset, ins.opname, ins.arg, ins.argval))
'''.replace("@@ROOT@@", _ROOT)

probe = os.path.join(tempfile.mkdtemp(), "probe.py")
with open(probe, "w", encoding="utf-8") as fh:
    fh.write(script)
out = subprocess.run(
    [os.path.join(_ROOT, "embed_python", "python-%s" % version, "python.exe"),
     probe, pyc, want or ""],
    capture_output=True, text=True,
)
sys.stdout.write(out.stdout)
sys.stderr.write(out.stderr)
