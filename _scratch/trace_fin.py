"""Trace the POP_BLOCK / finally path for finally_print on 3.9."""
import ast
import os
import sys
import py_compile
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser

SRC = "def f(p):\n    try:\n        g()\n    finally:\n        print(p)\n"

tmp = tempfile.mkdtemp()
p = os.path.join(tmp, "t.py")
c = os.path.join(tmp, "t.pyc")
with open(p, "w") as f:
    f.write(SRC)
py_compile.compile(p, cfile=c, doraise=True)
code = PyCParser.parse_file(c).code

dec = Decompiler()
fn = next(x for x in code.co_consts if hasattr(x, "co_code"))
ins = dec.dis.disassemble(fn)
for i, x in enumerate(ins):
    print("%3d %4d %-22s %r" % (i, x.offset, x.opname, x.argval))
print("pop_block for setup 0:", dec._find_pop_block(ins, 0, 20))
print("clause_len at 10:", dec._finally_clause_length(ins, 10))

orig_collect = dec._collect_finally_body


def traced_collect(code_, instructions, try_end_idx, handler_start_idx):
    r = orig_collect(code_, instructions, try_end_idx, handler_start_idx)
    print("[collect] try_end=%d handler=%d -> body=%s resume=%r" % (
        try_end_idx, handler_start_idx,
        [ast.dump(s)[:40] for s in r[0]], r[1]))
    return r


dec._collect_finally_body = traced_collect

orig_bare = dec._is_bare_finally


def traced_bare(instructions, handler_start_idx):
    r = orig_bare(instructions, handler_start_idx)
    print("[bare_finally] handler=%d -> %r" % (handler_start_idx, r))
    return r


dec._is_bare_finally = traced_bare

orig_parsed = dec._parse_except_handlers


def traced_parse(*a, **k):
    r = orig_parsed(*a, **k)
    print("[parse_handlers] -> %r" % (r if r is None else "handlers"))
    return r


dec._parse_except_handlers = traced_parse

print("-- output --")
print(dec.decompile(code))
