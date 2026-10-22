import sys, dis
kw = {"show_caches": False} if sys.version_info >= (3, 11) else {}
for name, src in {
    "bare_except": "def f():\n    try:\n        x = 1\n    except:\n        raise\n",
    "bare_except_pass": "def f():\n    try:\n        x = 1\n    except:\n        pass\n",
    "typed_raise": "def f():\n    try:\n        x = 1\n    except ValueError:\n        raise\n",
    "as_raise": "def f():\n    try:\n        x = 1\n    except ValueError as e:\n        raise\n",
}.items():
    print("===", name)
    code = compile(src, "<t>", "exec")
    fn = [c for c in code.co_consts if hasattr(c, "co_code")][0]
    for i in dis.get_instructions(fn, **kw):
        print("   %4d %-22s %s" % (i.offset, i.opname, repr(i.argval)))