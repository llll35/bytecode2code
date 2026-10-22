import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyvers import compile_source, decompile, interp

CASES = {
    "exceptstar": "def f(xs):\n"
                  "    try:\n"
                  "        for x in xs:\n"
                  "            pass\n"
                  "    except* ValueError as eg:\n"
                  "        return eg\n",
    "match": "def f(x):\n"
             "    match x:\n"
             "        case 0:\n"
             "            return 'zero'\n"
             "        case _:\n"
             "            return 'other'\n",
    "match2": "def f(p):\n"
              "    match p:\n"
              "        case {'k': v}:\n"
              "            return v\n"
              "        case [a, b]:\n"
              "            return a + b\n"
              "        case _:\n"
              "            return None\n",
}
tmp = tempfile.mkdtemp()
for v in ("3.11", "3.12"):
    print("=== %s ===" % v)
    for n, s in CASES.items():
        p = os.path.join(tmp, "%s_%s.pyc" % (n, v))
        try:
            compile_source(s, p, version=v, dfile="<p>")
            print("--- %s ---" % n)
            print(decompile(p).get("source", ""), end="")
        except Exception as exc:
            print("--- %s --- ERROR %s: %s" % (n, type(exc).__name__, exc))
    print()