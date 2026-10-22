import os
import sys
import functools

# Probe sources and outputs live in ./debug; the package itself is one level up.
BASE = os.path.dirname(os.path.abspath(__file__))
DEBUG = os.path.join(BASE, 'debug')
if DEBUG not in sys.path:
    sys.path.insert(0, DEBUG)
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def _run(label, src):
    base = DEBUG
    p = os.path.join(base, '_probe_%s.py' % label)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(src)
    c = os.path.join(base, '_probe_%s.pyc' % label)
    import py_compile
    py_compile.compile(p, cfile=c, doraise=True)
    sys.setrecursionlimit(3000)
    try:
        from bytecode2code.main import decompile_file
        out = decompile_file(c)
        print('%-10s OK  %d lines' % (label, len(out.splitlines())))
    except RecursionError as e:
        print('%-10s RECURSION' % label)
    except Exception as e:
        print('%-10s ERROR %s: %s' % (label, type(e).__name__, e))


def deco(fn):
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        return fn(*args, **kwargs)
    return inner


CASES = {
    'deco': (
        "import functools\n"
        "def deco(fn):\n"
        "    @functools.wraps(fn)\n"
        "    def inner(*a, **k):\n"
        "        return fn(*a, **k)\n"
        "    return inner\n"
        "@deco\n"
        "def f(a, b=2, *args, c, d=4, **kw):\n"
        "    return a + b\n"
    ),
    'boolops': (
        "def f(a, b):\n"
        "    t = 0\n"
        "    if a and b:\n"
        "        t += 1\n"
        "    if a or b:\n"
        "        t += 2\n"
        "    if not (a and b):\n"
        "        t -= 1\n"
        "    return t\n"
    ),
    'chaincmp': "def f(x):\n    return 0 < x <= 10 and x != 5 or x == -1\n",
    'lambda': (
        "def f(xs):\n"
        "    g = lambda x, y=1: x + y\n"
        "    h = lambda x: x if x > 0 else -x\n"
        "    return [g(i) for i in xs] + [h(i) for i in xs]\n"
    ),
    'fstring': (
        "def f(a, b, d):\n"
        "    return f\"{a:>{b}.{d}f} and {a!r:10} and {a:#x} and {b:{d}}\"\n"
    ),
    'ifexp2': "def f(a, b, c, d):\n    return (a if b else c) if d else (c if a else b)\n",
    'withstmt': "def f(p):\n    with open(p, encoding='utf-8') as fh:\n        d = fh.read()\n    return d\n",
    'nonlocal': (
        "def f(e):\n"
        "    g = e\n"
        "    def inner():\n"
        "        nonlocal g\n"
        "        g += 1\n"
        "        return g\n"
        "    return inner()\n"
    ),
    'starcall': "def f(a, b, c, *r, **kw):\n    args = [a, b, *r, c]\n    m = {**kw, 'z': 9}\n    return print(*args, **m)\n",
    'yield': (
        "def f(n):\n"
        "    acc = []\n"
        "    for i in range(n):\n"
        "        if i % 2:\n"
        "            acc.append(i)\n"
        "        yield i\n"
        "    yield from acc\n"
    ),
    'yieldexpr': (
        "def f(n):\n"
        "    g = (x * 2 for x in range(n))\n"
        "    yield from g\n"
        "    t = yield (n if n else 0)\n"
        "    return t\n"
    ),
    'slices': "def f(s, a, b):\n    return s[a:b:2] + s[...] + s[::-1]\n",
    'loops': (
        "def f(n):\n"
        "    t = 0\n"
        "    i = 0\n"
        "    while i < n:\n"
        "        if i == 3:\n"
        "            continue\n"
        "        if i > 10:\n"
        "            break\n"
        "        t += i\n"
        "        i += 1\n"
        "    else:\n"
        "        t = -1\n"
        "    for j in range(3):\n"
        "        for k in range(3):\n"
        "            if j == k:\n"
        "                break\n"
        "            t += j * k\n"
        "    return t\n"
    ),
    'comps': (
        "def f(n):\n"
        "    a = [x * 2 for x in range(n) if x % 2]\n"
        "    b = {k: v for k, v in zip(range(n), range(n, n * 2))}\n"
        "    c = {x for x in range(n) if x > 1}\n"
        "    d = tuple(x for x in range(n))\n"
        "    e = sum(x for x in range(n))\n"
        "    return a, b, c, d, e\n"
    ),
    'cls': (
        "class S:\n"
        "    kind = 's'\n"
        "    __slots__ = ('x', 'y')\n"
        "    def __init__(self, x=0, y=0):\n"
        "        self.x = x\n"
        "        self.y = y\n"
        "    @property\n"
        "    def norm(self):\n"
        "        return (self.x ** 2 + self.y ** 2) ** 0.5\n"
        "    @staticmethod\n"
        "    def unit():\n"
        "        return S(1, 1)\n"
        "    @classmethod\n"
        "    def origin(cls):\n"
        "        return cls()\n"
        "    def __repr__(self):\n"
        "        return f\"S({self.x}, {self.y})\"\n"
        "class T(S):\n"
        "    def norm(self):\n"
        "        return super().norm * 2\n"
    ),
    'swap': "def f(a, b, c):\n    a, b, c = b, c, a\n    (d, e), g = (a, b), c\n    return a, b, c, d, e, g\n",
    'walrus': "def f(items):\n    return [y for x in items if (y := x * 2) > 4]\n",
    'whileelse': "def f(n):\n    i = 0\n    while i < n:\n        i += 1\n    else:\n        i = -1\n    return i\n",
}

if __name__ == '__main__':
    for name, src in CASES.items():
        if len(sys.argv) > 1 and sys.argv[1] != name:
            continue
        _run(name, src)
