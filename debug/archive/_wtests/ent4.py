import sys, marshal
sys.path.insert(0, r"D:/py/bytecode2code")
from pyvers.decomp311 import _exception_entries
blob = open(r"D:/py/bytecode2code/_wtests/w4.pyc", "rb").read()
code = marshal.loads(blob[16:])
fcode = [c for c in code.co_consts if hasattr(c, "co_code")][0]
for e in _exception_entries(fcode):
    print("(%d,%d)->%d depth=%d" % (e[0], e[1], e[2], e[3]))
