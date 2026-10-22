"""Temporary: why does 3.11 async produce empty output?"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pyvers import dispatch, interp  # noqa: E402

RUNNER = r'''
import sys, os, marshal, dis
for p in (os.path.join(r"%ROOT%", "pyvers"), r"%ROOT%"):
    if p not in sys.path:
        sys.path.insert(0, p)
import decomp311
with open(sys.argv[1], "rb") as h:
    top = marshal.loads(h.read()[16:])
inner = [c for c in top.co_consts if hasattr(c, "co_code")][0]
print("inner flags", inner.co_flags, "iscoroutine",
      bool(inner.co_flags & 0x80))
out = decomp311.Rewriter(inner).run()
print("--- rewritten", len(out), "instrs ---")
for ins in out:
    print("%4s %-26s %s" % (ins.offset, ins.opname,
                            "" if ins.arg is None else ins.argval))
'''


def main():
    src = "async def f(p):\n    try:\n        await g()\n    except ValueError:\n        pass\n"
    for version in ("3.11",):
        with tempfile.TemporaryDirectory(prefix="a2_") as folder:
            pyc = os.path.join(folder, "m.pyc")
            runner = os.path.join(folder, "r.py")
            dispatch.compile_source(src, pyc, version=version, dfile="<a2>")
            with open(runner, "w", encoding="utf-8") as f:
                f.write(RUNNER.replace("%ROOT%", HERE))
            proc = subprocess.run(
                [interp.interpreter_path(version), runner, pyc],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
            print("=== %s" % version)
            print(proc.stdout.decode("utf-8", "replace"))


if __name__ == "__main__":
    main()