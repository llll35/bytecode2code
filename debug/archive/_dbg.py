import sys
sys.setrecursionlimit(3000)
import dis
import types
from bytecode2code.pyc_parser import PyCParser

code = PyCParser.parse_file(sys.argv[1]).code


def walk(co, depth=0):
    pad = "  " * depth
    print("%s### %s  flags=0x%x var=%s cell=%s free=%s" % (
        pad, co.co_name, co.co_flags, co.co_varnames, co.co_cellvars, co.co_freevars))
    for ins in dis.get_instructions(co):
        arg = ins.argval
        if isinstance(arg, types.CodeType):
            arg = "<code %s>" % arg.co_name
        print("%s  %3d %-24s %r" % (pad, ins.offset, ins.opname, arg))
    for const in co.co_consts:
        if isinstance(const, types.CodeType):
            print("")
            walk(const, depth + 1)


walk(code)
