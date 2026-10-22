import os, sys, tempfile
sys.path.insert(0, r"D:\py\bytecode2code")
from pyvers import compile_source, decompile, interp

# compile prime.py source with each version and decompile
src = open(r"D:\py\bytecode2code\tests\samples\prime.py", encoding="utf-8").read()
with tempfile.TemporaryDirectory() as d:
    for version in ("3.9", "3.11", "3.12"):
        pyc = os.path.join(d, version + ".pyc")
        compile_source(src, pyc, version=version)
        data = decompile(pyc)
        out = os.path.join(r"D:\py\bytecode2code\_scratch", "prime_out_%s.py" % version)
        open(out, "w", encoding="utf-8").write(data["source"])
        print("wrote", out, "mode=", data.get("mode"))
        try:
            compile(data["source"], "<out>", "exec")
            print("  parses OK")
        except SyntaxError as e:
            print("  SYNTAX ERROR:", e)
