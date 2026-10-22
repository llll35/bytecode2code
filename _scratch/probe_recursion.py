"""Run inside an embedded interpreter: instrument the loop reconstruction.

    embed_python\\python-3.12\\python.exe -B _scratch\\probe_recursion.py <pyc>
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from pyvers import decomp311, worker
from pyvers.pycfile import read_header

path = sys.argv[1]
code = worker.load_code(path, read_header(path).payload_offset)

orig_while_true = decomp311.Decompiler311._emit_while_true
orig_plain = decomp311.Decompiler311._handle_plain_jump
seen = {}


def wt(self, instr, instructions, idx, code, stack, stmts, head_idx, limit):
    key = (head_idx, instructions[head_idx].offset if head_idx < len(instructions) else None)
    seen[key] = seen.get(key, 0) + 1
    if seen[key] <= 4:
        print("while_true head_idx=%s offset=%s count=%s" % (key[0], key[1], seen[key]))
    return orig_while_true(self, instr, instructions, idx, code, stack, stmts, head_idx, limit)


def pj(self, instr, instructions, idx, code, stack, stmts, target, limit):
    print("plain_jump idx=%s off=%s target=%s loop_stack=%s" % (
        idx, instr.offset, target, self._loop_stack))
    return orig_plain(self, instr, instructions, idx, code, stack, stmts, target, limit)


decomp311.Decompiler311._emit_while_true = wt
decomp311.Decompiler311._handle_plain_jump = pj

sys.setrecursionlimit(200)
try:
    out = decomp311.Decompiler311().decompile(code)
    print("OK, %d chars" % len(out))
    print(out[:400])
except RecursionError:
    print("RECURSION at limit 200")