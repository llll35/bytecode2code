"""Dump retfinally a/b/c bytecode to compare return-in-finally shapes.

Usage: python -B _scratch/dbg_abc.py <version>
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pyvers import compile_source, disassemble

CASES = {
    "a": "def a():\n    try:\n        return 1\n    finally:\n        x = 1\n",
    "b": "def b():\n    try:\n        return 1\n    finally:\n        pass\n",
    "c": "def c(n):\n    try:\n        return n + 1\n    finally:\n        y = n * 2\n    return y\n",
}


def main():
    version = sys.argv[1]
    for name in ("a", "b", "c"):
        tmp = tempfile.mkdtemp()
        pyc = os.path.join(tmp, name + ".pyc")
        compile_source(CASES[name], pyc, version=version, dfile="<" + name + ">")
        text = disassemble(pyc).get("text", "")
        # only the nested code object disassembly
        idx = text.find("Disassembly of <code object")
        print("========== case %s ==========" % name)
        print(text[idx:].strip())
        print()


if __name__ == "__main__":
    main()
