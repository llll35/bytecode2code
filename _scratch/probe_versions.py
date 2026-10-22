"""Diff the source text pyvers produces for one probe across versions.

    .venv\\Scripts\\python.exe -B _scratch\\probe_versions.py 3.10 3.11
"""
import difflib
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pyvers import compile_source, decompile
from tests.cases import PROBES

VERSIONS = sys.argv[1:] or ["3.10", "3.11", "3.12"]
BASELINE = "3.9"


def render(version, source, tmp):
    pyc = os.path.join(tmp, "%s_%s.pyc" % (abs(hash(source)) % 10 ** 8, version))
    compile_source(source, pyc, version=version, dfile="<probe>")
    return decompile(pyc).get("source", "").splitlines()


def main():
    tmp = tempfile.mkdtemp()
    for name in sorted(PROBES):
        source = PROBES[name]
        base = render(BASELINE, source, tmp)
        for version in VERSIONS:
            got = render(version, source, tmp)
            if got == base:
                continue
            diff = [l for l in difflib.unified_diff(
                base, got, BASELINE, version, lineterm="", n=0)]
            print("=== %s on %s ===" % (name, version))
            print("\n".join("    " + l for l in diff))
            print()


if __name__ == "__main__":
    main()