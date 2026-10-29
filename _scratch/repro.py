"""Scratch: print the decompiled output of one probe under the running interpreter.

    python _scratch/repro.py finally_return
    embed_python/python-3.10/python.exe _scratch/repro.py finally_return
"""
import os
import py_compile
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.cases import FLOW_PROBES, PROBES
from tests.test_roundtrip import decompile_sample

name = sys.argv[1]
probes = PROBES if name.startswith("probe_") else FLOW_PROBES
source = probes[name]

with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "%s.py" % name)
    pyc_path = os.path.join(tmp, "%s.pyc" % name)
    with open(src_path, "w", encoding="utf-8") as handle:
        handle.write(source)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)
    print("### python %s" % sys.version.split()[0])
    print("### source")
    print(source)
    print("### decompiled")
    try:
        print(decompile_sample(pyc_path))
    except Exception as exc:
        print("ERROR %s: %s" % (type(exc).__name__, exc))
