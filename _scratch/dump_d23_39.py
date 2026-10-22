import dis

CASES = {
    "d2_try_break": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            if x:\n"
        "                break\n"
        "        finally:\n"
        "            x = 0\n"
        "    return x\n"
    ),
    "d3_two_levels": (
        "def f(x):\n"
        "    try:\n"
        "        try:\n"
        "            return 1\n"
        "        finally:\n"
        "            x = 1\n"
        "    finally:\n"
        "        x = 2\n"
    ),
    "d3_nested_finally": (
        "def f(x):\n"
        "    try:\n"
        "        try:\n"
        "            try:\n"
        "                return 1\n"
        "            finally:\n"
        "                x = 1\n"
        "        finally:\n"
        "            x = 2\n"
        "    finally:\n"
        "        x = 3\n"
    ),
    "d3_finally_with_except": (
        "def f(x):\n"
        "    try:\n"
        "        try:\n"
        "            raise ValueError(x)\n"
        "        except ValueError as e:\n"
        "            return e\n"
        "    finally:\n"
        "        x = 1\n"
    ),
}
for name, src in CASES.items():
    print("=" * 50, name)
    code = compile(src, "<s>", "exec")
    for c in code.co_consts:
        if hasattr(c, "co_code"):
            dis.dis(c)
