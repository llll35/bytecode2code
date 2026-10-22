import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code import decompiler as dc
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser

tmp = tempfile.mkdtemp()
src = ("def f(x):\n"
       "    try:\n"
       "        try:\n"
       "            pass\n"
       "        finally:\n"
       "            x = 1\n"
       "    finally:\n"
       "        x = 2\n"
       "    return 1\n")
p = os.path.join(tmp, "d3.pyc")
compile_source_to_pyc(src, p)
fn = [c for c in PyCParser.parse_file(p).code.co_consts if hasattr(c, "co_code")][0]

d = dc.Decompiler()
ins = d.dis.disassemble(fn)

orig_emit = d._emit_statements
depth = [0]


def emit(code, instructions, **kw):
    start = kw.get("start", 0)
    end = kw.get("end")
    depth[0] += 1
    print("%semit start=%s end=%s" % ("  " * depth[0], start, end))
    try:
        return orig_emit(code, instructions, **kw)
    finally:
        depth[0] -= 1


d._emit_statements = emit

orig_pi = d._process_instruction


def pi(instr, instructions, idx, code, stack, stmts, **kw):
    print("  %s[%d] %s%s" % ("  " * depth[0], idx, instr.opname,
                             (" argval=%r" % (instr.argval,)) if instr.arg is not None else ""))
    consumed = orig_pi(instr, instructions, idx, code, stack, stmts, **kw)
    print("  %s    -> consumed=%s stmts=%s stack=%s handled=%s"
          % ("  " * depth[0], consumed, [type(s).__name__ for s in stmts],
             [type(x).__name__ for x in stack], d._handled_ranges))
    return consumed


d._process_instruction = pi
print(d.decompile(PyCParser.parse_file(p).code))