"""Inspect one sample: show source, decompiled output and the round-trip diff.

    python -m debug.inspect probe_swap
    python -m debug.inspect prime --dis
"""

import os
import py_compile
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bytecode2code.main import decompile_file
from bytecode2code.pyc_parser import PyCParser
from tests.cases import FILE_SAMPLES, PROBES, SAMPLES
from tests.equivalence import compare


def show(name):
    name = name[6:] if name.startswith("probe_") else name
    if name in PROBES:
        source = PROBES[name]
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "p.py")
            pyc = os.path.join(tmp, "p.pyc")
            with open(src, "w", encoding="utf-8") as f:
                f.write(source)
            py_compile.compile(src, cfile=pyc, doraise=True)
            out = decompile_file(pyc)
            original = PyCParser.parse_file(pyc).code
    else:
        pyc = os.path.join(SAMPLES, FILE_SAMPLES[name])
        out = decompile_file(pyc)
        original = PyCParser.parse_file(pyc).code
        src = os.path.join(SAMPLES, FILE_SAMPLES[name][:-4] + ".py")
        if os.path.exists(src):
            with open(src, encoding="utf-8") as f:
                source = f.read()

    print("=" * 70)
    print("SOURCE")
    print("=" * 70)
    print(source)
    print("=" * 70)
    print("DECOMPILED")
    print("=" * 70)
    print(out)

    print("=" * 70)
    print("DIFFS")
    print("=" * 70)
    for diff in compare(original, compile(out, name + ".py", "exec")):
        print(" ", diff)


if __name__ == "__main__":
    for target in sys.argv[1:]:
        if not target.startswith("-"):
            show(target)
