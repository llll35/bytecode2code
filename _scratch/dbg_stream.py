"""Dump the synthetic 3.9-shaped stream the 3.11 rewriter emits for a probe."""
import importlib, os, py_compile, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.cases import FLOW_PROBES

name = sys.argv[1]
source = FLOW_PROBES[name]
version = "%d.%d" % sys.version_info[:2]
pkg = "py%sDecompiler" % version.replace(".", "")
parser = importlib.import_module(pkg + ".pyc_parser")

from tests.test_roundtrip import decompile_sample  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    sp = os.path.join(tmp, "p.py")
    pp = os.path.join(tmp, "p.pyc")
    with open(sp, "w", encoding="utf-8") as h:
        h.write(source)
    py_compile.compile(sp, cfile=pp, doraise=True)
    pc = parser.PyCParser()
    pc.parse(pp)
    code = pc.code

    if pkg != "py39Decompiler":
        decompmod = importlib.import_module(pkg + ".decomp311")
        from pkg = None  # placeholder

    from collections import deque
