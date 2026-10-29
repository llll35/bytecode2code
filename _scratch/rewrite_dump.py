"""Scratch: dump what ``decomp311.Rewriter`` hands the reader for a flow probe.

    embed_python/python-3.11/python.exe _scratch/rewrite_dump.py reraise_chain
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
cfg = importlib.import_module(pkg + ".cfg_flow")

with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "p.py")
    pyc_path = os.path.join(tmp, "p.pyc")
    with open(src_path, "w", encoding="utf-8") as handle:
        handle.write(source)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)
    code = parser.PyCParser.parse_file(pyc_path).code

inner = [c for c in code.co_consts if hasattr(c, "co_code") and c.co_name == fname]
target = inner[0] if inner else code
print("### python %s  code object %s" % (sys.version.split()[0], target.co_name))

print("### real dis (disassembler)")
dis_mod = importlib.import_module(pkg + ".disassembler")
real = dis_mod.Disassembler().disassemble(target)
for i, ins in enumerate(real):
    print("  %3d %5d %-26s %s" % (i, ins.offset, ins.opname, ins.argval))

print("### rewritten stream handed to the reader")
instructions = rewriter_mod.TranslatingDisassembler().disassemble(target)
for i, ins in enumerate(instructions):
    print("  %3d %5d %-26s %s" % (i, ins.offset, ins.opname, ins.argval))

print("### regions of the rewritten stream")
regions = cfg.ExceptionAnalyzer(instructions, cfg.build_cfg(instructions)).regions()
if not regions:
    print("  (none)")
for r in regions:
    print("  setup=%d(%s) kind=%s body=%s..%s pops=%s exit=%s handlers=%s" % (
        r.setup_index, instructions[r.setup_index].opname, r.kind, r.body_start,
        r.body_end, r.body_pops, r.exit_pops, r.handlers))
