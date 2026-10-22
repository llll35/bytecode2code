import dis

CASES = {
    "simple_a_and_b_or_c": "def f(x):\n    return x == 1 and x == 2 or x == 3\n",
    "simple_a_and_b_and_c_or_d": (
        "def f(x):\n    return x == 1 and x == 2 and x == 3 or x == 4\n"
    ),
    "simple_a_and_b_or_c_or_d": (
        "def f(x):\n    return x == 1 and x == 2 or x == 3 or x == 4\n"
    ),
    "chain_and_b_or_c_or_d": (
        "def f(x):\n"
        "    return 0 < x <= 10 and x != 5 or x == -1 or x > 100\n"
    ),
    "chain_and_b_and_c_or_d": (
        "def f(x):\n"
        "    return 0 < x <= 10 and x != 5 and x > 1 or x == -1\n"
    ),
    "chain_or_b_and_c": (
        "def f(x):\n    return 0 < x <= 10 or x == -1 and x > 2\n"
    ),
    "chain_or_b_and_c_and_d": (
        "def f(x):\n    return 0 < x <= 10 or x == -1 and x > 2 and x < 9\n"
    ),
    "a_and_chain_or_c": (
        "def f(x):\n    return x != 5 and 0 < x <= 10 or x == -1\n"
    ),
    "a_or_chain_and_c": (
        "def f(x):\n    return x == -1 or 0 < x <= 10 and x != 5\n"
    ),
    "chain3_and_b": "def f(x):\n    return 0 < x < 10 < 20 and x != 5\n",
    "chain_in_arg": "def f(x):\n    return g(0 < x <= 10)\n",
    "chain_in_arg_and": (
        "def f(x):\n    return g(0 < x <= 10) and h(x)\n"
    ),
    "chain_cond_stmt_and": (
        "def f(x):\n    if 0 < x <= 10 and x != 5:\n        return 1\n    return 2\n"
    ),
    "chain_cond_stmt_only": (
        "def f(x):\n    if 0 < x <= 10:\n        return 1\n    return 2\n"
    ),
}

for name, src in CASES.items():
    print("=" * 70)
    print(name)
    ns = {}
    exec(compile(src, "<t>", "exec"), ns)
    for ins in dis.get_instructions(ns["f"].__code__):
        print(
            "%4s %-28s %-6s"
            % (
                ins.offset,
                ins.opname,
                "" if ins.arg is None else "->%s" % (ins.argval,),
            )
        )
