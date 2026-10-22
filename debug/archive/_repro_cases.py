import os, sys, tempfile, ast
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers import compile_source, decompile

CASES = {
    "except return": "def f(p):\n    try:\n        return int(p)\n    except ValueError:\n        return 0\n",
    "finally print": "def f(p):\n    try:\n        g()\n    finally:\n        print(p)\n",
    "finally return": "def f(p):\n    try:\n        return int(p)\n    finally:\n        pass\n",
    "nested try": "def f(p):\n    try:\n        try:\n            g()\n        finally:\n            h()\n    except ValueError:\n        pass\n",
    "try loop": "def f(p):\n    for i in p:\n        try:\n            g(i)\n        finally:\n            h()\n",
    "try comprehension": "def f(p):\n    try:\n        return [x for x in p]\n    except ValueError:\n        return []\n",
}

with tempfile.TemporaryDirectory() as d:
    for name, src in CASES.items():
        print("############ %s ############" % name)
        print("--- SOURCE ---")
        print(src)
        for version in ("3.9", "3.11", "3.12"):
            pyc = os.path.join(d, "c_%s_%s.pyc" % (version, name.replace(" ", "_")))
            compile_source(src, pyc, version=version)
            data = decompile(pyc)
            print("--- %s ---" % version)
            print(data["source"])
        print()
