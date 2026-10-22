import os, sys, tempfile, ast
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers import compile_source, decompile
CASES = {
 "chain_return": "def f(a,b,c,d):\n    return a < b < c < d\n",
 "chain_not": "def f(a,b,c,d):\n    return not (a < b < c < d)\n",
 "chain_not_long": "def f(a,b,c,d,e):\n    return not (a < b < c < d < e)\n",
 "chain_store": "def f(a,b,c,d):\n    r = a < b < c < d\n    return r\n",
 "chain_tuple": "def f(a,b,c,d):\n    return (a < b < c < d, 1)\n",
 "chain_and_not": "def f(a,b,c,d,e):\n    r = a < b <= c != d is e\n    return r, not (a < b < c < d < e)\n",
}
with tempfile.TemporaryDirectory() as d:
    for name, src in CASES.items():
        print("######## %s ########" % name)
        for version in ("3.9","3.11","3.12"):
            pyc = os.path.join(d, "c_%s_%s.pyc" % (version, name))
            compile_source(src, pyc, version=version)
            out = decompile(pyc)["source"]
            try:
                same = ast.dump(ast.parse(out)) == ast.dump(ast.parse(src))
            except Exception as e:
                same = "PARSE ERR %s" % e
            print("--- %s (AST==src: %s) ---" % (version, same)); print(out)
