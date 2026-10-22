import dis
import sys

from bytecode2code.pyc_parser import PyCParser

orig = PyCParser.parse_file(r"debug\py39_syntax_demo.pyc").code
with open(r"debug\_p39_out.py", encoding="utf-8") as f:
    new = compile(f.read(), "_p39_out.py", "exec")


def all_codes(code, path="<module>"):
    yield path, code
    for c in code.co_consts:
        if hasattr(c, "co_name"):
            yield from all_codes(c, path + "." + c.co_name)


def norm(code):
    out = []
    for i in dis.get_instructions(code):
        a = i.argval
        if hasattr(a, "co_code"):
            a = "<code %s>" % a.co_name
        out.append((i.offset, i.opname, repr(a)))
    return out


a = list(all_codes(orig))
b = list(all_codes(new))
print("orig count", len(a), "new count", len(b))
for (pa, ca), (pb, cb) in zip(a, b):
    da, db = norm(ca), norm(cb)
    if da == db:
        continue
    print("=== %s DIFFERS ===" % pa)
    for k in range(max(len(da), len(db))):
        x = da[k] if k < len(da) else None
        y = db[k] if k < len(db) else None
        if x != y:
            print("   orig:", x)
            print("   new :", y)
