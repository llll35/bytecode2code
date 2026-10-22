import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyvers import compile_source, decompile

CASES = {
    "d3_two_levels": (
        "def f(x):\n"
        "    try:\n"
        "        try:\n"
        "            return 1\n"
        "        finally:\n"
        "            x = 1\n"
        "    finally:\n"
        "        x = 2\n"
    ),
    "d3_nested_finally": (
        "def f(x):\n"
        "    try:\n"
        "        try:\n"
        "            try:\n"
        "                return 1\n"
        "            finally:\n"
        "                x = 1\n"
        "        finally:\n"
        "            x = 2\n"
        "    finally:\n"
        "        x = 3\n"
    ),
}

tmp = tempfile.mkdtemp()
for version in ("3.11", "3.12"):
    print("=" * 30, version, "=" * 30)
    for name, src in CASES.items():
        pyc = os.path.join(tmp, "%s_%s.pyc" % (name, version))
        compile_source(src, pyc, version=version, dfile="<probe>")
        out = decompile(pyc).get("source", "")
        print("--- %s ---" % name)
        print(out)
        print()
