import sys, dis
kw = {"show_caches": False} if sys.version_info >= (3, 11) else {}
for name, src in {
    "local_bare": "def f():\n    x: int\n    return 1\n",
    "local_val": "def f():\n    x: int = 5\n    return x\n",
    "attr_val": "class S:\n    def __init__(self):\n        self.items: list = []\n",
    "mod_val": "x: int = 5\n",
    "mod_bare": "y: str\n",
}.items():
    print("===", name)
    code = compile(src, "<t>", "exec")
    def walk(c, ind="  "):
        print(ind + "<%s>" % c.co_name)
        for i in dis.get_instructions(c, **kw):
            print(ind + "   %4d %-24s %s" % (i.offset, i.opname, repr(i.argval)))
        for k in c.co_consts:
            if hasattr(k, "co_code"):
                walk(k, ind + "  ")
    walk(code)