"""Show, for one probe and one version: the original disassembly and the
decompiled source, so a round-trip difference can be read directly.

    embed_python/python-<V>/python.exe _scratch/dump_probe.py <V> <probe> [func]
"""
import dis
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

VERSION = sys.argv[1]
PROBE = sys.argv[2]
FUNC = sys.argv[3] if len(sys.argv) > 3 else None

from pyvers.decomp_compat import make_decompiler
from tests.cases import PROBES

source = PROBES[PROBE]
code = compile(source, PROBE + ".py", "exec")
dec = make_decompiler(VERSION)
out = dec.decompile(code)

print("=" * 70)
print("ORIGINAL SOURCE")
print("=" * 70)
print(source)

print("=" * 70)
print("DECOMPILED (%s)" % VERSION)
print("=" * 70)
print(out)


def dump(co, label):
    print("-" * 70)
    print(label)
    print("-" * 70)
    dis.dis(co)


if FUNC:
    for const in code.co_consts:
        if hasattr(const, "co_name") and const.co_name == FUNC:
            dump(const, "ORIGINAL %s" % FUNC)
    recompiled = compile(out, PROBE + ".py", "exec")
    for const in recompiled.co_consts:
        if hasattr(const, "co_name") and const.co_name == FUNC:
            dump(const, "RECOMPILED %s" % FUNC)
else:
    dump(code, "ORIGINAL module")
    dump(compile(out, PROBE + ".py", "exec"), "RECOMPILED module")
