import os, sys, tempfile
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers import compile_source, decompile

src = """
import contextlib

@contextlib.contextmanager
def cm(name):
    yield name

def f(a, b):
    with a as x, b as y:
        return x + y
"""

with tempfile.TemporaryDirectory() as d:
    for version in ("3.9", "3.10", "3.11", "3.12"):
        pyc = os.path.join(d, version + ".pyc")
        try:
            compile_source(src, pyc, version=version)
            data = decompile(pyc)
            print("=== %s ===" % version)
            print(data["source"])
        except Exception as exc:
            print("=== %s FAILED: %s ===" % (version, exc))
