"""Corpus used by the test suite.

Two kinds of samples:

``FILE_SAMPLES``
    ``.pyc`` files living in ``tests/samples``.  Those whose name also matches
    a ``.py`` file next to it additionally get an AST-level comparison.

``PROBES``
    Small syntax features kept here as source rather than as loose files, so the
    intent of each case stays readable and the ``.pyc`` is rebuilt on demand.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SAMPLES = os.path.join(HERE, "samples")
OUTPUTS = os.path.join(ROOT, "debug", "outputs")

#: name -> ``.pyc`` file name inside ``SAMPLES``
FILE_SAMPLES = {
    "prime": "prime.pyc",
    "checkerboard": "checkerboard.cpython-39.pyc",
    "py39_syntax_demo": "py39_syntax_demo.pyc",
    "feature_matrix": "feature_matrix.pyc",
}

PROBES = {
    "deco": (
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
    "boolops": (
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
    "chaincmp": "def f(x):\n    return 0 < x <= 10 and x != 5 or x == -1\n",
    "chaincond": (
        "def f(a, b):\n"
        "    t = 0\n"
        "    if 0 < a < 100:\n"
        "        t += 1\n"
        "    if 0 < a < 100 and b:\n"
        "        t += 2\n"
        "    if 0 < a < 10 < 100 and b:\n"
        "        t += 3\n"
        "    return t\n"
    ),
    "lambda": (
        "def f(xs):\n"
        "    g = lambda x, y=1: x + y\n"
        "    h = lambda x: x if x > 0 else -x\n"
        "    return [g(i) for i in xs] + [h(i) for i in xs]\n"
    ),
    "fstring": (
        "def f(a, b, d):\n"
        "    return f\"{a:>{b}.{d}f} and {a!r:10} and {a:#x} and {b:{d}}\"\n"
    ),
    "ifexp2": "def f(a, b, c, d):\n    return (a if b else c) if d else (c if a else b)\n",
    "withstmt": "def f(p):\n    with open(p, encoding='utf-8') as fh:\n        d = fh.read()\n    return d\n",
    # 3.12 has no jump from a ``with`` block's normal path to the code behind
    # it: it copies that code after the handler instead.  Both the plain and
    # the compound value exercise the copy, which used to be emitted twice.
    "withstmt_expr": "def f(p):\n    with open(p) as fh:\n        d = fh.read()\n    return d + 1\n",
    # A loop variable a nested function closes over lives in a cell, so the
    # compiler binds it with ``STORE_DEREF`` rather than ``STORE_FAST``.
    "cellloop": (
        "def f(items):\n"
        "    acc = []\n"
        "    for x in items:\n"
        "        acc.append(x)\n"
        "    def g():\n"
        "        return x\n"
        "    return acc, g\n"
    ),
    "nonlocal": (
        "def f(e):\n"
        "    g = e\n"
        "    def inner():\n"
        "        nonlocal g\n"
        "        g += 1\n"
        "        return g\n"
        "    return inner()\n"
    ),
    # A ``while`` nested directly in a ``for`` compiles its false branch as a
    # jump *back* to the enclosing iterator instead of forward to an exit, so
    # there is no forward target to bound the body with.
    "nested_while": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        while x:\n"
        "            x -= 1\n"
        "    return 1\n"
    ),
    "starcall": "def f(a, b, c, *r, **kw):\n    args = [a, b, *r, c]\n    m = {**kw, 'z': 9}\n    return print(*args, **m)\n",
    "yield": (
        "def f(n):\n"
        "    acc = []\n"
        "    for i in range(n):\n"
        "        if i % 2:\n"
        "            acc.append(i)\n"
        "        yield i\n"
        "    yield from acc\n"
    ),
    "yieldexpr": (
        "def f(n):\n"
        "    g = (x * 2 for x in range(n))\n"
        "    yield from g\n"
        "    t = yield (n if n else 0)\n"
        "    return t\n"
    ),
    "slices": "def f(s, a, b):\n    return s[a:b:2] + s[...] + s[::-1]\n",
    "loops": (
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
    "comps": (
        "def f(n):\n"
        "    a = [x * 2 for x in range(n) if x % 2]\n"
        "    b = {k: v for k, v in zip(range(n), range(n, n * 2))}\n"
        "    c = {x for x in range(n) if x > 1}\n"
        "    d = tuple(x for x in range(n))\n"
        "    e = sum(x for x in range(n))\n"
        "    return a, b, c, d, e\n"
    ),
    "cls": (
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
    "swap": "def f(a, b, c):\n    a, b, c = b, c, a\n    (d, e), g = (a, b), c\n    return a, b, c, d, e, g\n",
    "walrus": "def f(items):\n    return [y for x in items if (y := x * 2) > 4]\n",
    "whileelse": "def f(n):\n    i = 0\n    while i < n:\n        i += 1\n    else:\n        i = -1\n    return i\n",
    # ``del`` of anything but a plain name has no dedicated fast path.
    "delete": "def f(a):\n    del a[0]\n    del a.b\n    del a\n    return a\n",
    # ``assert`` is compiled into a jump over a raise, never into its own opcode.
    "assert": (
        "def f(a, b, E):\n"
        "    assert a\n"
        "    assert a, 'boom'\n"
        "    assert a.x, E('why')\n"
        "    return 1\n"
    ),
    # ``__build_class__`` takes keywords for the class keywords, so the class
    # reconstruction cannot live only in the positional CALL_FUNCTION branch.
    "classkw": (
        "class C(dict, metaclass=type):\n"
        "    x = 1\n"
        "class D(Base, metaclass=Meta, extra=1):\n"
        "    pass\n"
    ),
    # ``a = b = 1`` and ``(y := v)`` both start with a DUP_TOP.
    "chainedassign": (
        "a = b = 1\n"
        "def f(x, g):\n"
        "    p = q = r = x\n"
        "    if (y := x) > 1:\n"
        "        return y\n"
        "    return (n := g()) + p + q + r\n"
    ),
    # UNPACK_EX, the only opcode that records a starred target.
    "starred": (
        "def f(a, b, c, d):\n"
        "    *a, d = [1, 2, 3]\n"
        "    d, *a = [1, 2, 3]\n"
        "    d, *a, c = [1, 2, 3]\n"
        "    *a, = [1, 2, 3]\n"
        "    return a, d, c\n"
    ),
    # Relative imports carry their dot count in the IMPORT_NAME level operand.
    "relative_imports": (
        "from . import x\n"
        "from .mod import y\n"
        "from ..pkg.mod import y as z\n"
        "from os import path as p\n"
        "from os.path import *\n"
    ),
    # Chains longer than three links used to be re-associated into nested
    # comparisons, and the last two links used to be dropped entirely.
    "longchain": (
        "def f(a, b, c, d, e, g):\n"
        "    return a < b < c < d < e < g\n"
        "def h(a, b, c, d, e):\n"
        "    r = a < b <= c != d is e\n"
        "    return r, not (a < b < c < d < e)\n"
    ),
    # A nested code object must not inherit the enclosing scope's bookkeeping.
    "nested_imports": (
        "import sys\n"
        "def inner():\n"
        "    import json\n"
        "    import re\n"
        "    return sys.path\n"
        "class C:\n"
        "    def m(self):\n"
        "        import os\n"
        "        return os.sep\n"
    ),
    # The compiler closes every except chain with a bare RERAISE, which has no
    # source form; a try inside a loop must not turn the body's jump over the
    # handler into an ``else`` clause either.
    "exceptions": (
        "def f(n):\n"
        "    try:\n"
        "        x = int(n)\n"
        "    except ValueError as e:\n"
        "        print(e)\n"
        "    except TypeError:\n"
        "        raise\n"
        "    except:\n"
        "        raise ValueError('bad')\n"
        "    else:\n"
        "        return x\n"
        "    return None\n"
        "def g(n):\n"
        "    while True:\n"
        "        try:\n"
        "            parts = n.split(',')\n"
        "            break\n"
        "        except ValueError as e:\n"
        "            print(e)\n"
        "    results = []\n"
        "    for i in results:\n"
        "        try:\n"
        "            print(i)\n"
        "        except KeyError as e:\n"
        "            print(e)\n"
        "    return results\n"
    ),
    # ``except X as e`` parks the clause's exit sequence behind the compiler's
    # own ``e = None; del e`` cleanup, and the ``else`` sits between the body's
    # jump and the handler's merge point.
    "except_as": (
        "def a(n):\n"
        "    try:\n"
        "        x = int(n)\n"
        "    except ValueError as e:\n"
        "        return 1\n"
        "    return None\n"
        "def b(n):\n"
        "    try:\n"
        "        x = int(n)\n"
        "    except ValueError as e:\n"
        "        print(e)\n"
        "    else:\n"
        "        return x\n"
        "    return None\n"
        "def c(n):\n"
        "    try:\n"
        "        x = int(n)\n"
        "    except ValueError as e:\n"
        "        print(e)\n"
        "    except TypeError:\n"
        "        raise\n"
        "    except:\n"
        "        raise ValueError('bad')\n"
        "    else:\n"
        "        return x\n"
        "    return None\n"
        "def d(n):\n"
        "    try:\n"
        "        x = int(n)\n"
        "    except ValueError as e:\n"
        "        return len(e) * 2\n"
        "    return None\n"
    ),
    # A module level try/except must not swallow the definitions after it,
    # and an ``else`` clause has to stop where the handler merges.
    "controlflow": (
        "try:\n"
        "    import json\n"
        "except ImportError:\n"
        "    json = None\n"
        "class Later:\n"
        "    x = 1\n"
        "def later():\n"
        "    return 1\n"
        "class Other:\n"
        "    pass\n"
        "import os\n"
        "def clause(x):\n"
        "    try:\n"
        "        a = x\n"
        "    except ValueError:\n"
        "        a = 1\n"
        "    else:\n"
        "        a = 2\n"
        "    b = a + 1\n"
        "    return b\n"
        "def looped(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            y = x\n"
        "        except ValueError:\n"
        "            continue\n"
        "        if y:\n"
        "            break\n"
        "    return 1\n"
    ),
    # A ``return`` that is the last statement of a ``try``/``finally`` body is
    # compiled after the inline finally copy, so it has to be pulled back into
    # the body rather than left outside the ``try``.
    "retfinally": (
        "def a():\n"
        "    try:\n"
        "        return 1\n"
        "    finally:\n"
        "        x = 1\n"
        "def b():\n"
        "    try:\n"
        "        return 1\n"
        "    finally:\n"
        "        pass\n"
        "def c(n):\n"
        "    try:\n"
        "        return n + 1\n"
        "    finally:\n"
        "        y = n * 2\n"
        "    return y\n"
    ),
    # The value of a ``return`` that ends a ``try`` body is loaded *after* the
    # block pop, so the return itself is not part of the body the reader sees.
    "tryreturn": (
        "def a(p):\n"
        "    try:\n"
        "        g(p)\n"
        "        return 1\n"
        "    except ValueError:\n"
        "        pass\n"
        "def b(p):\n"
        "    try:\n"
        "        g(p)\n"
        "        return p + 1\n"
        "    except ValueError:\n"
        "        return 0\n"
    ),
    # A method call whose argument is itself a call nests two method loaders;
    # the outer one must survive the inner call.
    "nestedcall": (
        "def a(d, x):\n"
        "    d.append(str(x))\n"
        "def b(f, results):\n"
        "    f.write('\\n'.join(results))\n"
    ),
    # A ``finally`` clause runs from a handler of its own, so it must not be
    # read as the body of an ``except`` clause.
    "finallyclause": (
        "def a(p):\n"
        "    try:\n"
        "        g()\n"
        "    finally:\n"
        "        print(p)\n"
        "def b(p):\n"
        "    try:\n"
        "        d = int(p)\n"
        "    finally:\n"
        "        pass\n"
        "    return d\n"
        "def c(p):\n"
        "    try:\n"
        "        try:\n"
        "            g()\n"
        "        finally:\n"
        "            h()\n"
        "    except ValueError:\n"
        "        pass\n"
    ),
}
