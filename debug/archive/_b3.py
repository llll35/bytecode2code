"""Temporary: why 3.9 async comprehension is empty."""
import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pyvers  # noqa: E402

SRC = "async def f(p):\n    return [x async for x in p]\n"

RUNNER = r'''
import sys, os, marshal, types, traceback
sys.path.insert(0, os.path.join(sys.argv[2], "embed_python"))
sys.path.insert(0, os.path.join(sys.argv[2], "embed_python", "python-" + sys.argv[3]))
sys.path.insert(0, sys.argv[2])
from pyvers import worker
import pyvers.decomp_compat as dc
cls = dc.decompiler_for(sys.argv[3])
src = sys.argv[4]
try:
    print(worker.run_source(cls, src, sys.argv[1]))
except Exception:
    traceback.print_exc()
'''


def main():
    for version in ("3.9", "3.10"):
        folder = tempfile.mkdtemp(prefix="b3_")
        runner = os.path.join(folder, "r.py")
        with open(runner, "w", encoding="utf-8") as f:
            f.write(RUNNER)
        import subprocess
        from pyvers import interp
        proc = subprocess.run(
            [interp.interpreter_path(version), runner, folder, HERE, version, SRC],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        print("=== %s" % version)
        print(proc.stdout.decode("utf-8", "replace"))


if __name__ == "__main__":
    main()