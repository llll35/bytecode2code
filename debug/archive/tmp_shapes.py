"""Disassemble the boolean/chained-comparison shapes that must be parsed."""

import dis


def show(label, fn):
    print("=== %s ===" % label)
    dis.dis(fn)
    print()


def a1(x):
    return 0 < x <= 10 and x != 5 or x == -1


def a2(a, b, c):
    return a and b and c or a


def a3(a, b, c, d):
    return a and b or c and d


def a4(x):
    return 0 < x <= 10 and x != 5


def a5(x):
    return 0 < x <= 10 or x == -1


def a6(x):
    return x != 5 and 0 < x <= 10


def a7(x):
    return 0 < x <= 10 and x != 5 and x > -3


def a8(x):
    return 0 < x <= 10 or x == -1 or x > 100


def a9(x):
    return 0 < x < 10 < 20 and x != 5


def a10(a):
    if 0 < a < 100:
        return 1
    return 0


def a11(x):
    return 0 < x <= 10


for label, fn in [
    ("chain and b or c", a1),
    ("a and b and c or a", a2),
    ("a and b or c and d", a3),
    ("chain and b", a4),
    ("chain or c", a5),
    ("b and chain", a6),
    ("chain and b and c", a7),
    ("chain or c or d", a8),
    ("3-link chain and b", a9),
    ("statement chain", a10),
    ("chain only", a11),
]:
    show(label, fn)
