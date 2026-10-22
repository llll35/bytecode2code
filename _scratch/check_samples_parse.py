"""Decompile every sample source at 3.11/3.12 and check the output parses.

A cheap catastrophic-breakage check for the call/method analysis changes.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

V = "%d.%d" % sys.version_info[:2]
from pyvers.decomp_compat import make_decompiler

samples = [
    os.path.join(ROOT, "tests", "samples", name)
    for name in ("prime.py", "feature_matrix.py", "py39_syntax_demo.py",
                 "py310_syntax_demo.py", "py311_syntax_demo.py",
                 "py312_syntax_demo.py")
]

bad = 0
for path in samples:
    source = open(path, encoding="utf-8").read()
    try:
        code = compile(source, path, "exec")
    except SyntaxError as exc:
        print("%-28s source needs another version (%s)" % (os.path.basename(path), exc.msg))
        continue
    try:
        out = make_decompiler(V).decompile(code)
        ast.parse(out)
        print("%-28s parses" % os.path.basename(path))
    except Exception as exc:
        bad += 1
        print("%-28s FAILED %s: %s" % (os.path.basename(path), type(exc).__name__, exc))
print("\nPython %s: %d/%d parse" % (V, len(samples) - bad, len(samples)))
