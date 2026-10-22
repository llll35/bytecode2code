"""Dump 3.9 bytecode for with variants (run under 3.9)."""
import dis

CASES = {
    "single_return": "def f(a):\n    with a as x:\n        return x\n",
    "multi_return": "def f(a, b):\n    with a as x, b as y:\n        return x + y\n",
    "multi_body": "def f(a, b):\n    with a as x, b as y:\n        z = x + y\n    return z\n",
    "multi_break": "def f(a, b):\n    for i in a:\n        with a as x, b as y:\n            break\n",
    "single_break": "def f(a):\n    for i in a:\n        with a as x:\n            break\n",
}

for name, src in CASES.items():
    print("=" * 60)
    print(name)
    print("=" * 60)
    code = compile(src, "<s>", "exec")
    for c in code.co_consts:
        if hasattr(c, "co_code"):
            dis.dis(c)
