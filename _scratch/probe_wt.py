import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyvers import compile_source, decompile

CASES = {
    "wt_try": "def f(xs):\n"
              "    while True:\n"
              "        try:\n"
              "            x = next(xs)\n"
              "        except StopIteration:\n"
              "            break\n"
              "        if x:\n"
              "            continue\n",
    "wt_nested": "def f(xs):\n"
                 "    while True:\n"
                 "        for x in xs:\n"
                 "            if x:\n"
                 "                break\n"
                 "        else:\n"
                 "            break\n",
    "wt_with": "def f(xs):\n"
               "    while True:\n"
               "        with open(xs) as fh:\n"
               "            if fh:\n"
               "                break\n",
    "wt_return": "def f(xs):\n"
                 "    while True:\n"
                 "        x = next(xs)\n"
                 "        if x:\n"
                 "            return x\n",
}
tmp = tempfile.mkdtemp()
for v in ("3.11", "3.12"):
    print("=== %s ===" % v)
    for n, s in CASES.items():
        p = os.path.join(tmp, "%s_%s.pyc" % (n, v))
        try:
            compile_source(s, p, version=v, dfile="<p>")
            out = decompile(p).get("source", "")
            print("--- %s --- (%d chars)" % (n, len(out)))
            print(out, end="")
        except Exception as exc:
            print("--- %s --- ERROR %s: %s" % (n, type(exc).__name__, exc))
    print()