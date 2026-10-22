"""Cross-version check: compile each probe with every embedded interpreter,
decompile it back through pyvers, and compare the ASTs.

    .venv\\Scripts\\python.exe -B _scratch\\probe_crossversion.py [3.9 3.10 ...]
"""
import ast
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pyvers import compile_source, decompile, interp
from tests.cases import PROBES

VERSIONS = sys.argv[1:] or ["3.9", "3.10", "3.11", "3.12"]


def normalise(tree):
    """Drop line numbers so the two trees compare on structure only."""
    for node in ast.walk(tree):
        if hasattr(node, "lineno"):
            node.lineno = 0
            node.col_offset = 0
    return ast.dump(tree)


def main():
    missing = [v for v in VERSIONS if interp.interpreter_path(v) is None]
    if missing:
        print("no interpreter for %s" % ", ".join(missing))
    tmp = tempfile.mkdtemp()
    failures = 0
    for version in VERSIONS:
        if version in missing:
            continue
        print("=== Python %s ===" % version)
        for name in sorted(PROBES):
            source = PROBES[name]
            pyc = os.path.join(tmp, "%s_%s.pyc" % (name, version))
            try:
                compile_source(source, pyc, version=version, dfile="<probe>")
            except Exception as exc:
                print("  %-18s COMPILE ERROR %s: %s" % (name, type(exc).__name__, exc))
                failures += 1
                continue
            try:
                out = decompile(pyc).get("source", "")
            except Exception as exc:
                print("  %-18s DECOMPILE ERROR %s: %s" % (name, type(exc).__name__, exc))
                failures += 1
                continue
            try:
                got = ast.parse(out)
            except SyntaxError as exc:
                print("  %-18s SYNTAX ERROR line %s: %s" % (name, exc.lineno, exc.msg))
                print("      " + out.replace("\n", "\n      "))
                failures += 1
                continue
            if normalise(ast.parse(source)) != normalise(got):
                print("  %-18s AST DIFF" % name)
                print("      " + out.replace("\n", "\n      "))
                failures += 1
            else:
                print("  %-18s ok" % name)
    print("\n%d failing" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())