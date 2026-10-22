"""Temporary: 3.9 async for break/continue raw shape."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pyvers import dispatch, interp  # noqa: E402

RUNNER = r'''
import sys, dis
with open(sys.argv[1], "rb") as h:
    top = __import__("marshal").loads(h.read()[16:])
for c in top.co_consts:
    if hasattr(c, "co_code"):
        print("CODE", c.co_name)
        for ins in dis.get_instructions(c):
            print("   %4s %-28s %s" % (ins.offset, ins.opname, ins.argval))
'''

CASES = {
    "async for break": "async def f(p):\n    async for x in p:\n        if x:\n            break\n    print(9)\n",
    "async for continue": "async def f(p):\n    async for x in p:\n        if x:\n            continue\n        print(x)\n",
    "async with": "async def f(p):\n    async with p as h:\n        print(h)\n",
}


def main():
    for name in sorted(CASES):
        for version in ("3.9",):
            with tempfile.TemporaryDirectory(prefix="a8_") as folder:
                pyc = os.path.join(folder, "m.pyc")
                runner = os.path.join(folder, "r.py")
                dispatch.compile_source(CASES[name], pyc, version=version,
                                        dfile="<a8>")
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