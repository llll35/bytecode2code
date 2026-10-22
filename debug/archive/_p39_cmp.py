import dis
import sys

from bytecode2code.pyc_parser import PyCParser

orig = PyCParser.parse_file(r"debug\py39_syntax_demo.pyc").code
with open(r"debug\_p39_out.py", encoding="utf-8") as f:
    new = compile(f.read(), "_p39_out.py", "exec")


def find(code, name):
    for c in code.co_consts:
        if hasattr(c, "co_name"):
            if c.co_name == name:
                return c
            r = find(c, name)
            if r is not None:
                return r
    return None


name = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "-" else None
if name:
    orig, new = find(orig, name), find(new, name)

LO, HI = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (0, 10 ** 6)


def show(title, code):
    print("=== %s ===" % title)
    for i, ins in enumerate(dis.get_instructions(code)):
        if LO <= i <= HI:
            print("  %3d %5d %-28s %s" % (i, ins.offset, ins.opname, ins.argrepr))


show("ORIG", orig)
show("NEW", new)
