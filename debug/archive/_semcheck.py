"""Recursively compare the decompiled output against the original bytecode."""
import dis
import sys
import difflib

from bytecode2code.pyc_parser import PyCParser, collect_code_objects


def norm(code):
    out = []
    for ins in dis.get_instructions(code):
        arg = ins.argval
        if hasattr(arg, "co_code"):
            arg = "<code %s>" % arg.co_name
        elif isinstance(arg, str) and len(arg) > 40:
            arg = "<str %r>" % arg[:40]
        out.append((ins.offset, ins.opname, repr(arg)))
    return out


def norm_consts(code):
    """Non-instruction payload, e.g. a docstring that emits no bytecode at all."""
    out = []
    for k in code.co_consts:
        if hasattr(k, "co_code"):
            k = "<code %s>" % k.co_name
        elif isinstance(k, str) and len(k) > 40:
            k = "<str %r>" % k[:40]
        out.append(repr(k))
    return out


def first_diff(na, nb):
    """Return a short description of where the two instruction streams diverge."""
    for i, (x, y) in enumerate(zip(na, nb)):
        if x != y:
            return "idx %d: orig %s vs new %s" % (i, x, y)
    if len(na) != len(nb):
        longer = "orig" if len(na) > len(nb) else "new"
        items = na if len(na) > len(nb) else nb
        return "len %d vs %d, extra in %s: %s" % (
            len(na), len(nb), longer, " ".join(repr(i) for i in items[min(len(na), len(nb)):min(len(na), len(nb)) + 3]),
        )
    return "identical"


def compare(a, b, path, diffs):
    na, nb = norm(a), norm(b)
    if na != nb:
        diffs.append("%s: %s" % (path, first_diff(na, nb)))
    ca_, cb_ = norm_consts(a), norm_consts(b)
    if ca_ != cb_:
        diffs.append("%s consts: %s" % (path, first_diff(ca_, cb_)))
    ca = {c.co_name: c for _, c in collect_code_objects(a)[1:]}
    cb = {c.co_name: c for _, c in collect_code_objects(b)[1:]}
    for name in sorted(set(ca) | set(cb)):
        if name not in ca:
            diffs.append("%s.%s missing in original" % (path, name))
        elif name not in cb:
            diffs.append("%s.%s extra in decompiled" % (path, name))
        else:
            compare(ca[name], cb[name], "%s.%s" % (path, name), diffs)


def main():
    orig = PyCParser.parse_file(sys.argv[1]).code
    with open(sys.argv[2], encoding="utf-8") as f:
        new = compile(f.read(), sys.argv[2], "exec")
    diffs = []
    compare(orig, new, "<module>", diffs)
    if not diffs:
        print("FULLY IDENTICAL: all code objects match")
        return 0
    print("DIFFERENCES (%d):" % len(diffs))
    for d in diffs:
        print(d)
    return 1


if __name__ == "__main__":
    sys.exit(main())
