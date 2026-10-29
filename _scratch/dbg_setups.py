"""Scratch: print the Rewriter's block-stack decisions for one probe.

    embed_python/python-3.11/python.exe _scratch/dbg_setups.py reraise_chain
"""
import importlib
import os
import py_compile
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.cases import FLOW_PROBES

name = sys.argv[1]
fname = sys.argv[2] if len(sys.argv) > 2 else "f"
source = FLOW_PROBES[name]
version = "%d.%d" % sys.version_info[:2]
pkg = "py%sDecompiler" % version.replace(".", "")
parser = importlib.import_module(pkg + ".pyc_parser")
rewriter_mod = importlib.import_module(pkg + ".decomp311")

with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "p.py")
    pyc_path = os.path.join(tmp, "p.pyc")
    with open(src_path, "w", encoding="utf-8") as handle:
        handle.write(source)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)
    code = parser.PyCParser.parse_file(pyc_path).code

inner = [c for c in code.co_consts if hasattr(c, "co_code") and c.co_name == fname]
target = inner[0] if inner else code

rw = rewriter_mod.Rewriter(target)
print("### try_setups   ", rw.try_setups)
print("### try_closes   ", rw.try_closes)
print("### empty bodies ", rw.empty_body_setups)
print("### _drops       ", sorted(rw._drops))
print("### handler heads", sorted(rw._handler_heads))
print("### with setups  ", rw.with_setups, rw.with_closes)
print("### try_before   ", rw.try_before)
print("### try_replace  ", {k: v for k, v in rw.try_replace.items()})
print("### _retarget    ", rw._retarget)
print("### _loop_breaks ", rw._loop_breaks)
entries = rewriter_mod._exception_entries(target)
print("### entries")
for e in sorted(entries, key=lambda x: (x[0], x[2])):
    print("   ", tuple(e))
out = rw.run()
print("### emitted stream (idx | offset | opname | arg)")
for i, ins in enumerate(out):
    print("  %3d | %5s | %-26s %s" % (i, getattr(ins, "offset", "?"),
                                      ins.opname, ins.argval))
