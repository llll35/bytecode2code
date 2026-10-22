"""Decompile a named probe with a chosen version and show the result.

usage: python _scratch\probe.py <version> <probe-name>
"""
import ast
import difflib
import os
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from tests import cases  # noqa: E402

version = sys.argv[1]
name = sys.argv[2]
source = cases.PROBES[name]

with tempfile.TemporaryDirectory() as folder:
    pyc = os.path.join(folder, "case.pyc")
    subprocess.run(
        [sys.executable, os.path.join(_ROOT, "_scratch", "try.py"), version, "-"],
        input=source, capture_output=True, text=True,
    )
    out = subprocess.run(
        [sys.executable, os.path.join(_ROOT, "_scratch", "try.py"), version, "-"],
        input=source, capture_output=True, text=True,
    )
    got = out.stdout
    if out.returncode != 0:
        got = out.stdout + out.stderr

print("--- source ---")
print(source, end="")
print("--- decompiled ---")
print(got, end="")
print("--- ast diff ---")
try:
    left = ast.dump(ast.parse(source))
    right = ast.dump(ast.parse(got))
    if left == right:
        print("identical")
    else:
        import ast as _ast
        a = _ast.dump(ast.parse(source), indent=1).splitlines()
        b = _ast.dump(ast.parse(got), indent=1).splitlines()
        for line in list(difflib.unified_diff(a, b, "source", "got", lineterm=""))[:80]:
            print(line)
except SyntaxError as exc:
    print("!! SyntaxError: %s (line %s)" % (exc.msg, exc.lineno))
