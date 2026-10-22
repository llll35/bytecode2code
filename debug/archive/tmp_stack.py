"""Verify the stack model for chained comparisons in value position."""
import dis
import itertools


def simulate(code, varnames, argvals, consts, ns):
    """Return (returned value, final stack depth) using documented semantics."""
    stack = []
    pc = 0
    instrs = list(dis.get_instructions(code))
    off2idx = {ins.offset: i for i, ins in enumerate(instrs)}
    steps = 0
    while pc < len(instrs):
        ins = instrs[pc]
        steps += 1
        if steps > 10000:
            raise RuntimeError("loop")
        op = ins.opname
        if op in ("LOAD_CONST", "LOAD_FAST", "LOAD_GLOBAL"):
            stack.append(
                consts[ins.arg] if op == "LOAD_CONST" else argvals.get(ins.argval, "<name>")
            )
        elif op == "DUP_TOP":
            stack.append(stack[-1])
        elif op == "ROT_TWO":
            stack[-1], stack[-2] = stack[-2], stack[-1]
        elif op == "ROT_THREE":
            stack[-3:] = [stack[-1], stack[-3], stack[-2]]
        elif op == "COMPARE_OP":
            b = stack.pop()
            a = stack.pop()
            import operator
            fn = {
                "<": operator.lt,
                "<=": operator.le,
                ">": operator.gt,
                ">=": operator.ge,
                "==": operator.eq,
                "!=": operator.ne,
            }[ins.argval]
            stack.append(fn(a, b))
        elif op == "UNARY_NOT":
            stack[-1] = not stack[-1]
        elif op == "CONTAINS_OP":
            b = stack.pop()
            a = stack.pop()
            stack.append((b in a) if ins.arg == 0 else (b not in a))
        elif op == "POP_TOP":
            stack.pop()
        elif op == "CALL_FUNCTION":
            args = [stack.pop() for _ in range(ins.arg)][::-1]
            f = stack.pop()
            if not callable(f):
                return ("<unresolved %r>" % (f,), len(stack))
            stack.append(f(*args))
        elif op == "JUMP_IF_FALSE_OR_POP":
            if stack[-1]:
                stack.pop()
                pc += 1
            else:
                pc = off2idx[ins.argval]
        elif op == "JUMP_IF_TRUE_OR_POP":
            if stack[-1]:
                pc = off2idx[ins.argval]
            else:
                stack.pop()
                pc += 1
        elif op == "LOAD_GLOBAL":
            stack.append(ns[ins.argval])
        elif op == "POP_JUMP_IF_FALSE":
            if stack[-1]:
                pc += 1
            else:
                stack.pop()
                pc = off2idx[ins.argval]
        elif op == "POP_JUMP_IF_TRUE":
            if stack[-1]:
                stack.pop()
                pc = off2idx[ins.argval]
            else:
                pc += 1
        elif op == "JUMP_FORWARD":
            pc = off2idx[ins.argval]
        elif op == "STORE_FAST":
            argvals[ins.argval] = stack.pop()
            pc += 1
        elif op == "RETURN_VALUE":
            return (stack.pop(), len(stack))
        elif op in ("RESUME", "NOP", "GEN_START", "CACHE", "PRECALL", "POP_TOP_IF_NONE"):
            pc += 1
        else:
            raise RuntimeError("unhandled %s" % op)
    return (None, len(stack))


def check(src, values):
    ns = {}
    exec(compile(src, "<t>", "exec"), ns)
    fn = ns["f"]
    bad = []
    for x in values:
        got = simulate(
            fn.__code__,
            list(fn.__code__.co_varnames),
            {"x": x},
            fn.__code__.co_consts,
            ns,
        )
        want = fn(x)
        if got[0] != want or got[1] != 0:
            bad.append((x, got, want))
    return bad


CALLS = []


def g(v):
    CALLS.append(v)
    return v


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
    "simple_a_and_b_or_c": "def f(x):\n    return x == 1 and x == 2 or x == 3\n",
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
    "not_a": "def f(x):\n    return not (0 < x <= 10)\n",
    "a_in_b": "def f(x):\n    return (0 < x <= 10) in (1, 2)\n",
    "assign_a_and_b": "def f(x):\n    y = 0 < x <= 10 and x != 5\n    return y\n",
    "assign_a": "def f(x):\n    y = 0 < x <= 10\n    return y\n",
    "chain_in_arg_and": "def f(x):\n    return g(0 < x <= 10) and x > 1\n",
}

values = [-100, -1, 0, 1, 2, 4, 5, 6, 9, 10, 11, 19, 20, 21, 100]
for name, src in CASES.items():
    bad = check(src, values)
    print("%-26s %s" % (name, "OK" if not bad else "MISMATCH %s" % (bad[:3],)))
