import sys, marshal, dis
sys.path.insert(0, r"D:/py/bytecode2code")
from pyvers.decomp311 import Rewriter, _exception_entries
blob = open(r"D:/py/bytecode2code/_wtests/w4.pyc", "rb").read()
code = marshal.loads(blob[16:])
fcode = [c for c in code.co_consts if hasattr(c, "co_code")][0]
dis.dis(fcode)
rw = Rewriter(fcode)
ins = rw.run()
print("== translated ==")
for i in ins:
    print(f"  {i.offset:4d} {i.opname:24s} {i.argrepr} jt={i.is_jump_target}")
print("== closes:", rw.with_closes, " swaps:", rw.with_swaps, " setups:", rw.with_setups, " async:", rw.async_with_setups, " exits:", rw.with_exits)
