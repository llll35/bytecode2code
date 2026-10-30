"""Decompile one flow probe under the running interpreter and dump the source."""
import os
import py_compile
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.cases import FLOW_PROBES
from tests.equivalence import compare
from tests.test_roundtrip import _check, decompile_sample

name = sys.argv[1]
source = FLOW_PROBES[name]

tmp = tempfile.mkdtemp()
src_path = os.path.join(tmp, name + ".py")
pyc_path = os.path.join(tmp, name + ".pyc")
with open(src_path, "w", encoding="utf-8") as f:
    f.write(source)
py_compile.compile(src_path, cfile=pyc_path, doraise=True)

out = decompile_sample(pyc_path)
print("=" * 30, "ORIGINAL", "=" * 30)
print(source)
print("=" * 30, "DECOMPILED", "=" * 30)
print(out)
res = _check("flow_" + name, pyc_path, out, keep=False)
print("=" * 30, "DIFF", res.ok, "=" * 30)
for d in res.diffs:
    print(d)
