"""Temporary: 3.11 SEND shape for yield-from vs await."""
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
        print("CODE", c.co_name)
        for ins in dis.get_instructions(c):
            print("   %4s %-28s %s" % (ins.offset, ins.opname, ins.argval))
'''

CASES = {
    "yield from stmt": "def f(p):\n    yield from p\n",
    "yield from value": "def f(p):\n    r = yield from p\n    return r\n",
    "await stmt": "async def f(p):\n    await g()\n",
    "await value": "async def f(p):\n    r = await g()\n    return r\n",
}


def main():
    for name in sorted(CASES):
        for version in ("3.9", "3.11"):
            with tempfile.TemporaryDirectory(prefix="a4_") as folder:
                pyc = os.path.join(folder, "m.pyc")
                runner = os.path.join(folder, "r.py")
                dispatch.compile_source(CASES[name], pyc, version=version,
                                        dfile="<a4>")
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