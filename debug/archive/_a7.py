"""Temporary: for/else baseline vs async for."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pyvers  # noqa: E402

CASES = {
    "for else": "def f(p):\n    for x in p:\n        print(x)\n    else:\n        print(9)\n",
    "for": "def f(p):\n    for x in p:\n        print(x)\n",
    "async for else": "async def f(p):\n    async for x in p:\n        print(x)\n    else:\n        print(9)\n",
    "async for": "async def f(p):\n    async for x in p:\n        print(x)\n",
    "async for break": "async def f(p):\n    async for x in p:\n        if x:\n            break\n    print(9)\n",
    "async for continue": "async def f(p):\n    async for x in p:\n        if x:\n            continue\n        print(x)\n",
}


def run(source, version):
    folder = tempfile.mkdtemp(prefix="a7_")
    path = os.path.join(folder, "m.pyc")
    pyvers.compile_source(source, path, version=version)
    return pyvers.decompile(path)["source"]


def main():
    for name in sorted(CASES):
        print("=" * 60)
        print("### %s" % name)
        print(CASES[name].rstrip())
        for version in ("3.9", "3.11"):
            try:
                out = run(CASES[name], version)
            except Exception as exc:  # noqa: BLE001
                out = "<<ERROR %s: %s>>" % (type(exc).__name__, exc)
            print("--- %s" % version)
            print(out.rstrip() or "<<EMPTY>>")


if __name__ == "__main__":
    main()