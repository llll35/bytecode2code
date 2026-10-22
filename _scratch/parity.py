import os, sys, tempfile, ast, difflib
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers import compile_source, decompile
from tests.cases import PROBES

names = ["assert","comps","except_as","exceptions","longchain","starred","swap","delete","relative_imports","yieldexpr"]
with tempfile.TemporaryDirectory() as d:
    for name in names:
        src = PROBES[name]
        outs = {}
        for version in ("3.9","3.11","3.12"):
            pyc = os.path.join(d, "p_%s_%s.pyc" % (version, name))
            try:
                compile_source(src, pyc, version=version)
                outs[version] = decompile(pyc)["source"]
            except Exception as e:
                outs[version] = "!! %s" % e
        print("######## %s ########" % name)
        # compare AST 3.9 vs 3.11/3.12
        for version in ("3.11","3.12"):
            try:
                a39 = ast.dump(ast.parse(outs["3.9"]))
            except Exception as e:
                a39 = "39 PARSE ERR %s" % e
            try:
                av = ast.dump(ast.parse(outs[version]))
            except Exception as e:
                av = "PARSE ERR %s" % e
            print("  %s AST equal to 3.9: %s" % (version, a39 == av))
        if outs["3.9"] != outs["3.12"]:
            print("  --- 3.9 ---"); print("   " + outs["3.9"].replace("\n","\n   "))
            print("  --- 3.12 ---"); print("   " + outs["3.12"].replace("\n","\n   "))
