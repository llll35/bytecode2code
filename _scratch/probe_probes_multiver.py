"""Run the probe corpus round-trip under the interpreter of a given version.

    embed_python/python-<V>/python.exe _scratch/probe_probes_multiver.py <V>

Prints one line per probe: OK / DIFF, plus the reason.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

VERSION = sys.argv[1] if len(sys.argv) > 1 else "%d.%d" % sys.version_info[:2]

from pyvers.decomp_compat import make_decompiler
from tests.cases import PROBES
from tests.equivalence import compare

dec = make_decompiler(VERSION)

failed = []
for name, source in sorted(PROBES.items()):
    try:
        original = compile(source, name + ".py", "exec")
    except SyntaxError as exc:
        print("  %-22s SOURCE SYNTAX %s" % (name, exc))
        failed.append(name)
        continue
    try:
        out = dec.decompile(original)
    except Exception as exc:
        print("  %-22s ERROR %s: %s" % (name, type(exc).__name__, exc))
        failed.append(name)
        continue
    try:
        recompiled = compile(out, name + ".py", "exec")
    except SyntaxError as exc:
        print("  %-22s SYNTAX %s" % (name, exc.msg))
        failed.append(name)
        continue
    diffs = compare(original, recompiled)
    if diffs:
        print("  %-22s DIFF" % name)
        for diff in diffs[:3]:
            print("        " + diff)
        failed.append(name)
    else:
        print("  %-22s OK" % name)

print("\nPython %s: %d/%d identical" % (VERSION, len(PROBES) - len(failed), len(PROBES)))
