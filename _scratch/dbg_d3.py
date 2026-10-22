"""Dump disassembly + IR for the D3 cases at a given version.

Usage: python -B _scratch/dbg_d3.py <case> <version>
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pyvers import compile_source, disassemble, dump_ir

CASES = {
    "two_levels": (
        "def f(x):\n"
        "    try:\n"
        "        try:\n"
        "            return 1\n"
        "        finally:\n"
        "            x = 1\n"
        "    finally:\n"
        "        x = 2\n"
    ),
    "nested_finally": (
        "def f(x):\n"
        "    try:\n"
        "        try:\n"
        "            try:\n"
        "                return 1\n"
        "            finally:\n"
        "                x = 1\n"
        "        finally:\n"
        "            x = 2\n"
        "    finally:\n"
        "        x = 3\n"
    ),
    "finally_with_except": (
        "def f(x):\n"
        "    try:\n"
        "        try:\n"
        "            raise ValueError(x)\n"
        "        except ValueError as e:\n"
        "            return e\n"
        "    finally:\n"
        "        x = 1\n"
    ),
}


def main():
    name = sys.argv[1]
    version = sys.argv[2]
    source = CASES[name]
    tmp = tempfile.mkdtemp()
    pyc = os.path.join(tmp, "%s_%s.pyc" % (name, version))
    compile_source(source, pyc, version=version, dfile="<dbg>")
    data = disassemble(pyc)
    print("=== NATIVE DISASSEMBLY (%s, %s) ===" % (name, version))
    print(data.get("text", data))
    print("\n=== IR ===")
    ir = dump_ir(pyc)
    print(json.dumps(ir, indent=1, ensure_ascii=False)[:6000])


if __name__ == "__main__":
    main()
