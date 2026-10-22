"""Disassemble BoolOp value-position shapes to learn the canonical CFG."""

import dis


def show(label, fn):
    print("=== %s ===" % label)
    dis.dis(fn)
    print()


def b1(a, b, c):
    return a and b and c


def b2(a, b, c):
    return a and b or c


def b3(a, b, c):
    return a or b and c


def b4(a, b, c, d):
    return a and b and c and d


def b5(a, b, c, d):
    return a and b and c or d


def b6(a, b, c, d):
    return a and (b and c) or d


def b7(a, b, c, d):
    return a or b or c


def b8(a, b, c, d):
    return a or b or c and d


def b9(a, b, c, d):
    return (a and b) and (c or d)


def b10(a, b, c, d):
    return a and b and c and d or a


for label, fn in [
    ("a and b and c", b1),
    ("a and b or c", b2),
    ("a or b and c", b3),
    ("a and b and c and d", b4),
    ("a and b and c or d", b5),
    ("a and (b and c) or d", b6),
    ("a or b or c", b7),
    ("a or b or c and d", b8),
    ("(a and b) and (c or d)", b9),
    ("a and b and c and d or a", b10),
]:
    show(label, fn)
