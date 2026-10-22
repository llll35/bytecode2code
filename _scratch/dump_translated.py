"""Run inside an embedded interpreter: show the stream the 3.9 decompiler sees.

    embed_python\\python-3.12\\python.exe -B _scratch\\dump_translated.py <pyc>
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from pyvers import decomp311, worker
from pyvers.pycfile import read_header


def walk(code, decom):
    instrs = decom.dis.disassemble(code)
    print("--- %s ---" % code.co_name)
    for i, x in enumerate(instrs):
        print("%3d %4d %-24s %s" % (i, x.offset, x.opname, repr(x.argval)))
    for const in code.co_consts:
        if hasattr(const, "co_code"):
            walk(const, decom)


path = sys.argv[1]
code = worker.load_code(path, read_header(path).payload_offset)
decom = decomp311.Decompiler311()
walk(code, decom)
print("=== decompiled ===")
print(decom.decompile(code))