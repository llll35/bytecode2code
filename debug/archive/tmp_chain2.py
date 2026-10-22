import dis
import sys

print(sys.version)

CASES = {
    "a_and_b_or_c": "def f(x):\n    return 0 < x <= 10 and x != 5 or x == -1\n",
    "a_and_b": "def f(x):\n    return 0 < x <= 10 and x != 5\n",
    "a_or_b": "def f(x):\n    return 0 < x <= 10 or x == -1\n",
    "b_and_a": "def f(x):\n    return x != 5 and 0 < x <= 10\n",
    "b_or_a": "def f(x):\n    return x == -1 or 0 < x <= 10\n",
    "a_and_b_and_c": "def f(x):\n    return 0 < x <= 10 and x != 5 and x > -3\n",
    "a_or_b_or_c": "def f(x):\n    return 0 < x <= 10 or x == -1 or x > 100\n",
    "a_and_b_or_c_and_d": (
        "def f(x):\n"
        "    return 0 < x <= 10 and x != 5 or x == -1 and x > 2\n"
    ),
    "assign_a_and_b": "def f(x):\n    y = 0 < x <= 10 and x != 5\n    return y\n",
    "assign_a": "def f(x):\n    y = 0 < x <= 10\n    return y\n",
    "not_a": "def f(x):\n    return not (0 < x <= 10)\n",
    "a_in_b": "def f(x):\n    return (0 < x <= 10) in (1, 2)\n",
    "stmt_a_and_b": "def f(x):\n    if 0 < x <= 10 and x != 5:\n        return 1\n    return 2\n",
    "stmt_a": "def f(x):\n    if 0 < x <= 10:\n        return 1\n    return 2\n",
    "a_and_b_or_c_left": (
        "def f(x):\n    return x == -1 or 0 < x <= 10 and x != 5\n"
    ),
}

for name, src in CASES.items():
    print("=" * 70)
    print(name)
    ns = {}
    exec(compile(src, "<t>", "exec"), ns)
    fn = ns["f"]
    for ins in dis.get_instructions(fn.__code__):
        print(
            "%4s %-28s %-6s %s"
            % (ins.offset, ins.opname, ins.argrepr, "" if ins.arg is None else "->%s" % (ins.argval,))
        )
