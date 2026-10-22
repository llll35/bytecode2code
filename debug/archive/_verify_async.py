"""Quick async comprehension fix verification."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pyvers  # noqa: E402

def run(source, version):
    folder = tempfile.mkdtemp(prefix="q_")
    path = os.path.join(folder, "m.pyc")
    pyvers.compile_source(source, path, version=version)
    return pyvers.decompile(path)["source"]

# Test 1: async comprehension module-level (the main bug)
src = "async def f(p):\n    return [x async for x in p]\n"
print("=== async comprehension ===")
for v in ("3.9", "3.10", "3.11", "3.12"):
    try:
        out = run(src, v)
        print(f"{v}: {repr(out[:80])}")
    except Exception as e:
        print(f"{v}: ERROR {e}")

# Test 2: Verify no regression on basic async
src2 = "async def f(p):\n    await g()\n"
print("\n=== basic await ===")
for v in ("3.9", "3.10", "3.11", "3.12"):
    try:
        out = run(src2, v)
        print(f"{v}: {repr(out[:80])}")
    except Exception as e:
        print(f"{v}: ERROR {e}")

# Test 3: async with
src3 = "async def f(p):\n    async with p as h:\n        print(h)\n"
print("\n=== async with ===")
for v in ("3.9", "3.10", "3.11", "3.12"):
    try:
        out = run(src3, v)
        print(f"{v}: {repr(out[:80])}")
    except Exception as e:
        print(f"{v}: ERROR {e}")
