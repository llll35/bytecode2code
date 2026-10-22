import dis

CASES = {
    "multi_body": "def f(a, b):\n    with a as x, b as y:\n        z = x + y\n    return z\n",
    "three_return": "def f(a, b, c):\n    with a as x, b as y, c as z:\n        return x\n",
}
for name, src in CASES.items():
    print("=" * 50, name)
    code = compile(src, "<s>", "exec")
    for c in code.co_consts:
        if hasattr(c, "co_code"):
            dis.dis(c)
