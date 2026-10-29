"""Scratch: dump the exception table of a flow probe's function code object.

    embed_python/python-3.11/python.exe _scratch/exc_table.py finally_return
"""
import dis
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.cases import FLOW_PROBES

name = sys.argv[1]
source = FLOW_PROBES[name]
code = compile(source, name + ".py", "exec")
version = sys.version.split()[0]
print("### python", version)

for const in [code] + [c for c in code.co_consts if hasattr(c, "co_code")]:
    if not hasattr(const, "co_exceptiontable"):
        continue
    print("-- %s --" % const.co_name)
    for entry in dis._parse_exception_table(const):
        print("   %s" % (entry,))
    print("   instructions:")
    for instr in dis.get_instructions(const):
        if getattr(instr, "starts_line", True) or True:
            print("   %5d %-28s %s%s" % (
                instr.offset, instr.opname, instr.argrepr,
                "  <== handler" if instr.is_jump_target and instr.opname in (
                    "PUSH_EXC_INFO", "COPY", "LOAD_CONST") else ""))
