"""Temporary: raw shapes for all async constructs."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pyvers import dispatch, interp  # noqa: E402

RUNNER = r'''
import sys, os, marshal, dis
with open(sys.argv[1], "rb") as h:
    top = marshal.loads(h.read()[16:])
for c in top.co_consts:
    if hasattr(c, "co_code"):
        print("CODE", c.co_name, "flags", c.co_flags)
        for ins in dis.get_instructions(c):
            print("   %4s %-26s %s" % (ins.offset, ins.opname, ins.argval))
'''

CASES = {
    "await simple": "async def f(p):\n    r = await g()\n    return r\n",
    "async for": "async def f(p):\n    async for x in p:\n        print(x)\n",
    "async with": "async def f(p):\n    async with g() as h:\n        print(h)\n",
    "async comp": "async def f(p):\n    return [x async for x in p]\n",
    "async gen": "async def f(p):\n    return [x for x in p]\n",
}


def main():
    for name in sorted(CASES):
        for version in ("3.9", "3.11"):
            with tempfile.TemporaryDirectory(prefix="a3_") as folder:
                pyc = os.path.join(folder, "m.pyc")
                runner = os.path.join(folder, "r.py")
                dispatch.compile_source(CASES[name], pyc, version=version,
                                        dfile="<a3>")
                with open(runner, "w", encoding="utf-8") as f:
                    f.write(RUNNER)
                proc = subprocess.run(
                    [interp.interpreter_path(version), runner, pyc],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120)
                print("=== %s %s" % (name, version))
                print(proc.stdout.decode("utf-8", "replace"))


if __name__ == "__main__":
    main()