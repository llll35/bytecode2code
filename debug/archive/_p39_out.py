"""
Python 3.9 全部新增语法 / 关键特性演示。
运行要求：CPython 3.9+
在 3.8 上会直接抛 SyntaxError（语法部分）或 AttributeError（API 部分）。
"""
from __future__ import annotations
import ast
import functools
import math
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Annotated, Final, Generic, Literal, TypeVar, get_type_hints
if sys.version_info < (3, 9):
    raise RuntimeError('本文件需要 Python 3.9 或更高版本')
T = TypeVar('T')
R = TypeVar('R')
int_list: list[int] = [1, 2, 3]
pair: dict[str, tuple[int, ...]] = {'a': (1, 2)}
frozen: frozenset[str] = frozenset({'x'})
the_type: type[int] = int
cb: Callable[[int, str], bool] = lambda i, s: bool(i) and bool(s)
seq: Sequence[int] = [1, 2]
alias = list[int]
origin = alias.__origin__
args = alias.__args__

class Stack(Generic[T]):
    """PEP 585 + PEP 612 的普通泛型类写法（3.9 起可写 list[T]）"""

    def __init__(self) -> None:
        self._items = []

    def push(self, item: T) -> None:
        self._items.append(item)

    def pop(self) -> T:
        return self._items.pop()

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

class IntList(list[int]):
    pass
Port = Annotated[int, 'TCP/UDP 端口', 0]
StrictStr = Annotated[str, '禁止为空']
WriteMode = Literal['w', 'a', 'x', 'r+']
MAX_CONNECTIONS: Final = 512

class Registry:

    def __init__(self, event: str) -> None:
        self.event = event
        self.handlers = []

    def on(self, phase: str) -> Callable[[Callable[[], None]], Callable[[], None]]:

        def decorator(fn: Callable[[], None]) -> Callable[[], None]:
            self.handlers.append(fn)
            return fn
        return decorator

    def __call__(self, fn: Callable[[], None]) -> Callable[[], None]:
        return fn
EVENTS: list[Registry] = [Registry('click'), Registry('scroll')]

@EVENTS[0].on('pressed')
def on_pressed() -> None:
    print('pressed')

@lambda fn: fn
def identity() -> None:
    print('identity')

@EVENTS[1].on('phase')
def handler() -> None:
    print('scroll phase')
F = TypeVar('F', bound=Callable[..., object])

def with_extra_logging(fn: F) -> F:
    """3.9 里用 bound=Callable 的 TypeVar 做签名保持装饰器；
    PEP 612 的 ParamSpec 写法（fn: Callable[P, R] / *args: P.args）
    要到 Python 3.10 才可用。"""

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        return fn(*args, **kwargs)
    return wrapper

@with_extra_logging
def compute(a: int, b: int=2) -> int:
    return a * b
base = {'id': 1, 'name': 'ada', 'deprecated': True}
extra = {'name': 'grace', 'year': 1815}
merged = base | extra
merged_overwrites = {**base, **extra}
base |= {'extra_flag': True}
frozen_map = {}.fromkeys(['a', 'b'], 0)
from_zip = dict(zip(int_list, pair['a']))
module = 'package.module'
short = module.removeprefix('package.')
doc_name = 'report.final.pdf'
stem = doc_name.removesuffix('.pdf')
no_change = ''.removeprefix('x')

def write_pair(first: str, second: str) -> tuple[int, int]:
    tmp = Path(tempfile.gettempdir())
    (a_path, b_path) = (tmp / '3.9_a.txt', tmp / '3.9_b.txt')
    with a_path.open('w', encoding='utf-8') as fa:
        with b_path.open('w', encoding='utf-8') as fb:
            fa.write(first)
            fb.write(second)
    return (a_path.stat().st_size, b_path.stat().st_size)

def guarded() -> str:
    with Path(tempfile.gettempdir()):
        with suppress(ZeroDivisionError):
            1 / 0
    return 'ZeroDivisionError 已被 suppress'

@functools.cache
def fib(n: int) -> int:
    return n if n < 2 else fib(n - 1) + fib(n - 2)

def unparse_demo() -> str:
    tree = ast.parse('x: list[int] = [i for i in range(10) if i % 2]')
    return ast.unparse(tree)

def now_in_tz() -> datetime:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        tz = ZoneInfo('Asia/Shanghai')
    except ZoneInfoNotFoundError:
        from datetime import timezone
        tz = timezone(28800, 'CST')
    return datetime.now(tz)

def topo() -> list[str]:
    from graphlib import TopologicalSorter
    graph = {'app': ['db', 'cache'], 'db': [], 'cache': ['db']}
    ts = TopologicalSorter(graph)
    return list(ts.static_order())

def math_bits() -> tuple[int, float, float]:
    return (math.lcm(4, 6, 10), math.nextafter(1.0, 2.0), math.ulp(0.001))
extra_metadata = get_type_hints(write_pair, include_extras=True)

def main() -> None:
    stack = Stack()
    for n in (1, 2, 3):
        stack.push(n)
    demo = {'PEP585 泛型别名': (alias, origin, args, the_type, IntList, seq), '泛型类 Stack': (stack.pop(), list(Stack[int]())), '签名保持装饰器': compute(3, 4), 'PEP614 装饰器': (on_pressed, identity, handler), 'PEP593 Annotated': (Port, StrictStr, WriteMode, MAX_CONNECTIONS, extra_metadata), 'PEP584 dict 联合': (merged, merged_overwrites, base), 'removeprefix/suffix': (short, stem, no_change), 'PEP617 括号化 with': (write_pair('a', 'bb'), guarded()), 'functools.cache': fib(30), 'ast.unparse': unparse_demo(), 'zoneinfo': now_in_tz().isoformat(), 'graphlib': topo(), 'math 3.9': math_bits(), 'fromkeys/zip': (frozen_map, from_zip)}
    for (key, value) in demo.items():
        print(f'{key:<20} -> {value}')
if __name__ == '__main__':
    main()