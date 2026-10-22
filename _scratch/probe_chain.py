import sys, dis
kw = {"show_caches": False} if sys.version_info >= (3, 11) else {}
for name, src in {
    "c2": "def f(a, b):\n    return a < b\n",
    "c3": "def f(a, b, c):\n    return a < b < c\n",
    "c4": "def f(a, b, c, d):\n    return a < b < c < d\n",
    "c5": "def f(a, b, c, d, e):\n    return a < b < c < d < e\n",
}.items():
    print("===", name)
    code = compile(src, "<t>", "exec")
    fn = [c for c in code.co_consts if hasattr(c, "co_code")][0]
    for i in dis.get_instructions(fn, **kw):
        print("   %4d %-22s %s" % (i.offset, i.opname, repr(i.argval)))