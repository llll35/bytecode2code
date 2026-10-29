"""Scratch: disassemble a flow probe's source and its decompiled output.

    python _scratch/dis.py finally_return
"""
import dis
import os
import py_compile
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.cases import FLOW_PROBES
from tests.test_roundtrip import decompile_sample

name = sys.argv[1]
source = FLOW_PROBES[name]
out = None
with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "%s.py" % name)
    pyc_path = os.path.join(tmp, "%s.pyc" % name)
    with open(src_path, "w", encoding="utf-8") as handle:
        handle.write(source)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)
    out = decompile_sample(pyc_path)

print("### python %s" % sys.version.split()[0])
print("### ORIGINAL SOURCE")
print(source)
print("### DECOMPILED")
print(out)


def _dump(label, code, fname):
    print("### %s" % label)
    for const in [code] + [c for c in code.co_consts if hasattr(c, "co_code")]:
        if const.co_name != fname:
            continue
        print("-- %s --" % const.co_name)
        dis.dis(const)
        if hasattr(const, "co_exceptiontable"):
            print(const.co_exceptiontable)


_dump("ORIGINAL BYTECODE", compile(source, "orig.py", "exec"), "f")
_dump("ROUND-TRIPPED BYTECODE", compile(out, "out.py", "exec"), "f")
