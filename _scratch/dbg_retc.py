"""Dump the retfinally case c bytecode.

Usage: python -B _scratch/dbg_retc.py <version>
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pyvers import compile_source, disassemble

SOURCE = (
    "def c(n):\n"
    "    try:\n"
    "        return n + 1\n"
    "    finally:\n"
    "        y = n * 2\n"
    "    return y\n"
)


def main():
    version = sys.argv[1]
    tmp = tempfile.mkdtemp()
    pyc = os.path.join(tmp, "c.pyc")
    compile_source(SOURCE, pyc, version=version, dfile="<c>")
    print(disassemble(pyc).get("text", ""))


if __name__ == "__main__":
    main()
