"""Scratch: dump the CFG regions + handler-body decisions for a flow probe.

    embed_python/python-3.10/python.exe _scratch/dbg_flow.py finally_return
"""
import os
import py_compile
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.cases import FLOW_PROBES

name = sys.argv[1]
source = FLOW_PROBES[name]

version = "%d.%d" % sys.version_info[:2]
pkg = "py%sDecompiler" % version.replace(".", "")
import importlib
mod = importlib.import_module(pkg)
parser = importlib.import_module(pkg + ".pyc_parser")
decompiler_mod = importlib.import_module(pkg + ".decompiler")
cfg_mod = importlib.import_module(pkg + ".cfg_flow")

with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "p.py")
    pyc_path = os.path.join(tmp, "p.pyc")
    with open(src_path, "w", encoding="utf-8") as handle:
        handle.write(source)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)
    parsed = parser.PyCParser.parse_file(pyc_path)
    code = parsed.code

print("### python", sys.version.split()[0], "package", pkg)
dis_mod = importlib.import_module(pkg + ".disassembler")
dis_ = dis_mod.Disassembler()

for const in [code] + [c for c in code.co_consts if hasattr(c, "co_code")]:
    if const.co_name != "f":
        continue
    instructions = dis_.disassemble(const)
    print("### instructions (index: offset opname arg)")
    for i, ins in enumerate(instructions):
        print("  %3d %5d %-24s %s" % (i, ins.offset, ins.opname, ins.argval))
    regions = cfg_mod.ExceptionAnalyzer(instructions, cfg_mod.build_cfg(instructions)).regions()
    print("### regions")
    for r in regions:
        print("  setup=%d(%s) kind=%s body=%s..%s pops=%s exit_pops=%s handlers=%s" % (
            r.setup_index, instructions[r.setup_index].opname, r.kind,
            r.body_start, r.body_end, r.body_pops, r.exit_pops,
            [(h, k) for h, k in r.handlers]))

print("### traced _parse_handler_body")
Base = decompiler_mod.Decompiler
orig = Base._parse_handler_body


def traced(self, code, instructions, body_start, as_setup_target, as_setup_idx,
           fallback_reraise_idx):
    out = orig(self, code, instructions, body_start, as_setup_target,
               as_setup_idx, fallback_reraise_idx)
    print("  body_start=%d fallback_reraise=%s as_setup=%s -> post=%d body=%s" % (
        body_start, fallback_reraise_idx, as_setup_idx, out[1],
        [type(s).__name__ for s in out[0]]))
    return out


Base._parse_handler_body = traced
print("### output")
try:
    print(mod.decompile(code))
except Exception as exc:
    print("ERROR %s: %s" % (type(exc).__name__, exc))
