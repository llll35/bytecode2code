"""Decompile a snippet (or file) with a chosen embedded interpreter.

usage: python _scratch\try.py <version> <file.py>
       python _scratch\try.py <version> - <<< "source"
"""
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from pyvers import dispatch, pycfile  # noqa: E402


def main():
    version = sys.argv[1]
    if sys.argv[2] == "-":
        source = sys.stdin.read()
    else:
        with open(sys.argv[2], encoding="utf-8") as fh:
            source = fh.read()
    with tempfile.TemporaryDirectory() as folder:
        pyc = os.path.join(folder, "case.pyc")
        dispatch.compile_source(source, pyc, version=version, dfile="<probe>")
        data = dispatch.decompile(pyc)
        print(data["source"])


if __name__ == "__main__":
    main()
