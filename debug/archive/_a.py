"""Temporary: how does await compile / read back on each version?"""
import ast
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pyvers  # noqa: E402
from pyvers import dispatch, interp  # noqa: E402

RUNNER = r'''
import sys, os, marshal, dis
for p in (os.path.join(r"%ROOT%", "pyvers"), r"%ROOT%"):
    if p not in sys.path:
        sys.path.insert(0, p)
with open(sys.argv[1], "rb") as h:
    top = marshal.loads(h.read()[16:])
def walk(code, path):
    yield path, code
    for c in code.co_consts:
        if hasattr(c, "co_code"):
            yield from walk(c, path + "/" + c.co_name)
for path, code in walk(top, top.co_name):
    if "await" in code.co_name or "f" in code.co_name:
        print("CODE", path, "flags=%d" % code.co_flags)
        for ins in dis.get_instructions(code):
            print("   %4s %-26s %s" % (ins.offset, ins.opname, ins.argval))
        break
'''


def raw(source, version):
    with tempfile.TemporaryDirectory(prefix="a_") as folder:
        pyc = os.path.join(folder, "m.pyc")
        runner = os.path.join(folder, "r.py")
        dispatch.compile_source(source, pyc, version=version, dfile="<a>")
        with open(runner, "w", encoding="utf-8") as f:
            f.write(RUNNER.replace("%ROOT%", HERE))
        proc = subprocess.run([interp.interpreter_path(version), runner, pyc],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=120)
        return proc.stdout.decode("utf-8", "replace")


def main():
    srcs = {
        "await call": "async def f(p):\n    await g()\n    return 1\n",
        "await try": ("async def f(p):\n    try:\n        await g()\n"
                      "    except ValueError:\n        pass\n"),
    }
    for name in sorted(srcs):
        for version in ("3.9", "3.11"):
            print("=== raw %s %s" % (name, version))
            print(raw(srcs[name], version))
        for version in ("3.9", "3.10", "3.11", "3.12"):
            with tempfile.TemporaryDirectory(prefix="a_") as folder:
                pyc = os.path.join(folder, "m.pyc")
                try:
                    dispatch.compile_source(srcs[name], pyc, version=version,
                                            dfile="<a>")
                    got = pyvers.decompile(pyc)["source"]
                except Exception as exc:
                    print("--- read %s %s: ERR %s: %s"
                          % (name, version, type(exc).__name__, exc))
                    continue
            print("--- read %s %s: %r" % (name, version, got))


if __name__ == "__main__":
    main()