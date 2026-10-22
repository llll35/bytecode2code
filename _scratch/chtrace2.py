import sys, os, marshal, py_compile, tempfile
sys.path.insert(0, r"D:\py\bytecode2code")
from bytecode2code import Decompiler as Base
from bytecode2code.decompiler import ast
from pyvers.decomp311 import Rewriter
src = "def f(a,b,c,d):\n    return a < b < c < d\n"
d = tempfile.mkdtemp(); p = os.path.join(d,"s.py"); open(p,"w").write(src)
pyc = os.path.join(d,"s.pyc"); py_compile.compile(p, cfile=pyc, dfile="<s>", doraise=True)
with open(pyc,"rb") as fh:
    fh.read(16); code = marshal.loads(fh.read())
fn = [c for c in code.co_consts if hasattr(c,"co_code")][0]
tl = Rewriter(fn).run()

# replicate _parse_value_chain with debug
def dvc(self, code, instructions, start, marker, end, stack):
    vals = self._eval_ifexp_expr(code, instructions, start, marker, stack)
    print("vals=", None if vals is None else len(vals), "expect", len(stack)+2)
    if vals is None or len(vals) != len(stack) + 2:
        print("  FAIL at vals"); return None
    left, mid = vals[-2], vals[-1]
    ops = [self._compare_op(instructions[marker + 2])]
    comparators = [mid]
    i = marker + 3; after = i; cont_idx = i
    while True:
        if i >= end or instructions[i].opname not in ("JUMP_IF_FALSE_OR_POP","JUMP_IF_TRUE_OR_POP"):
            print("  FAIL guard at i=%s op=%s" % (i, instructions[i].opname if i<len(instructions) else None)); return None
        fail_offset = self._jump_target(instructions[i]); fail_idx = self._find_target_idx(instructions, fail_offset)
        print("  i=%s fail_offset=%s fail_idx=%s" % (i, fail_offset, fail_idx))
        if not i < fail_idx or fail_idx + 1 >= len(instructions):
            print("  FAIL i<fail_idx"); return None
        if instructions[fail_idx].opname != "ROT_TWO" or instructions[fail_idx+1].opname != "POP_TOP":
            print("  FAIL cleanup", instructions[fail_idx].opname, instructions[fail_idx+1].opname); return None
        cont_idx = fail_idx + 2
        if cont_idx > end:
            print("  FAIL cont_idx>end"); return None
        nxt_cmp = self._find_value_chain_compare(instructions, i+1, fail_idx)
        if nxt_cmp is None:
            print("  FAIL nxt_cmp"); return None
        rhs = self._eval_ifexp_expr(code, instructions, i+1, nxt_cmp, [mid])
        if rhs is None or len(rhs) != 2:
            print("  FAIL rhs", rhs); return None
        ops.append(self._compare_op(instructions[nxt_cmp])); comparators.append(rhs[-1]); mid = rhs[-1]; after = nxt_cmp + 1
        if after < fail_idx and instructions[after].opname in ("JUMP_IF_FALSE_OR_POP","JUMP_IF_TRUE_OR_POP") and self._jump_target(instructions[after]) == fail_offset:
            i = after; continue
        print("  break: after=%s fail_idx=%s cont_idx=%s end=%s" % (after, fail_idx, cont_idx, end))
        break
    if after < fail_idx:
        print("  after<fail_idx, op=%s cont_op=%s" % (instructions[after].opname, instructions[cont_idx].opname))
        if instructions[after].opname == "JUMP_FORWARD":
            if self._find_target_idx(instructions, self._jump_target(instructions[after])) != cont_idx:
                print("  FAIL jump target"); return None
        elif not (instructions[after].opname == "RETURN_VALUE" and instructions[cont_idx].opname == "RETURN_VALUE"):
            print("  FAIL final position"); return None
    elif after != cont_idx:
        print("  FAIL after != cont_idx"); return None
    print("  OK cont_idx=%s" % cont_idx)
    return (list(stack) + [ast.Compare(left=left, ops=ops, comparators=comparators)], cont_idx)

Base._parse_value_chain = dvc
class ForceDis:
    def __init__(self, instrs): self.instrs = instrs
    def disassemble(self, code, show_lineno=True): return self.instrs
    def disassemble_to_str(self, code, show_header=True, show_lineno=True):
        return "\n".join(i.opname for i in self.instrs)
dec = Base(); dec.dis = ForceDis(tl)
print(dec.decompile(fn))
