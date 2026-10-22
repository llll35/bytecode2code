import sys
sys.path.insert(0, r"D:\py\bytecode2code")

import ast
from bytecode2code.decompiler import Decompiler
from bytecode2code.disassembler import Disassembler

SRC = "def f(a, b, c, d):\n    return (a if b else c) if d else (c if a else b)\n"
code = compile(SRC, "<s>", "exec")
fn = code.co_consts[0]
insts = Disassembler().disassemble(fn)

dec = Decompiler()
stack = []
stmts = []
print("ifexp:", dec._try_emit_ifexp(fn, insts, 0, len(insts), stack, stmts, allow_return=True))
print(ast.unparse(ast.Module(body=stmts, type_ignores=[])))
