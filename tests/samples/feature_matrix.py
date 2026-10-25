import functools


def deco(fn):
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        return fn(*args, **kwargs)
    return inner


@deco
def decorated(a, b=2, *args, c, d=4, **kwargs):
    total = a + b
    if a and b:
        total += 1
    if a or b:
        total += 2
    if not (a and b):
        total -= 1
    if 0 < a < 100:
        total *= 2
    return total


def lambdas(xs):
    f = lambda x, y=1: x + y
    g = lambda x: x if x > 0 else -x
    return [f(i) for i in xs] + [g(i) for i in xs]


def fstrings(a, b, d):
    return f"{a:>{b}.{d}f} and {a!r:10} and {a:#x} and {b:{d}}"


def nested_ifexp(a, b, c, d):
    return (a if b else c) if d else (c if a else b)


def with_stmt(path):
    with open(path, encoding='utf-8') as fh:
        data = fh.read()
    return data


def globals_and_nonlocal(path, extra):
    global _G
    _G = extra

    def inner():
        _G += 1
        return _G
    return inner()


def nonlocals(extra):
    _G = extra

    def inner():
        nonlocal _G
        _G += 1
        return _G
    return inner()


def star_calls(a, b, c, *rest, **kw):
    args = [a, b, *rest, c]
    merged = {**kw, 'z': 9}
    return print(*args, **merged)


def yields(n):
    acc = []
    for i in range(n):
        if i % 2:
            acc.append(i)
        yield i
    yield from acc


def slices(seq, a, b):
    return seq[a:b:2] + seq[...] + seq[::-1]


def loops(n):
    total = 0
    i = 0
    while i < n:
        if i == 3:
            continue
        if i > 10:
            break
        total += i
        i += 1
    else:
        total = -1
    for j in range(3):
        for k in range(3):
            if j == k:
                break
            total += j * k
    return total


def comps(n):
    a = [x * 2 for x in range(n) if x % 2]
    b = {k: v for k, v in zip(range(n), range(n, n * 2))}
    c = {x for x in range(n) if x > 1}
    d = tuple(x for x in range(n))
    e = sum(x for x in range(n))
    return a, b, c, d, e


class Shape:
    kind = 'shape'
    __slots__ = ('x', 'y')

    def __init__(self, x=0, y=0):
        self.x = x
        self.y = y

    @property
    def norm(self):
        return (self.x ** 2 + self.y ** 2) ** 0.5

    @staticmethod
    def unit():
        return Shape(1, 1)

    @classmethod
    def origin(cls):
        return cls()

    def __repr__(self):
        return f"Shape({self.x}, {self.y})"


class Sub(Shape):
    def norm(self):
        return super().norm * 2


def chain(x):
    return 0 < x <= 10 and x != 5 or x == -1


def unpack_and_swap(a, b, c):
    a, b, c = b, c, a
    (d, e), f = (a, b), c
    return a, b, c, d, e, f


def walrus_like(items):
    return [y for x in items if (y := x * 2) > 4]
