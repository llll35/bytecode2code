import dis

CASES = {
    "finally_print": "def f(p):\n    try:\n        g()\n    finally:\n        print(p)\n",
    "nested_try": (
        "def f(p):\n    try:\n        try:\n            g()\n"
        "        finally:\n            h()\n    except ValueError:\n        pass\n"
    ),
}
for name, src in CASES.items():
    print("=" * 50, name)
    code = compile(src, "<s>", "exec")
    for c in code.co_consts:
        if hasattr(c, "co_code"):
            dis.dis(c)
