"""
Python 3.10 全部新增语法 / 关键特性演示。
运行要求：CPython 3.10+
在 3.9 上会抛 SyntaxError（match 语句等语法部分）或 TypeError / AttributeError
（int | str 联合类型、dataclass(slots=True)、KW_ONLY 等运行时特性）。
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import itertools
import operator
import statistics
import sys
import tempfile
from dataclasses import KW_ONLY, dataclass
from pathlib import Path
from typing import (
    Any,
    Callable,
    Concatenate,
    Optional,
    ParamSpec,
    Tuple,
    TypeAlias,
    TypeGuard,
    TypeVar,
    Union,
    cast,
)

if sys.version_info < (3, 10):
    raise RuntimeError("本文件需要 Python 3.10 或更高版本")


# =====================================================================
# 1. PEP 634 —— 结构化模式匹配 match / case（本版本最重要的新语法）
#    match / case 是软关键字：变量名仍可叫 match、case、_。
#    支持：字面量 / 捕获 / 通配 `_` / 值 / 类（关键字与位置）/ 序列 /
#          映射（含 **rest）/ 或模式 `|` / as 捕获 / if 卫语句 guard。
# =====================================================================
class Point:
    __match_args__ = ("x", "y")           # 允许类模式写 Point(0, y)

    def __init__(self, x: int, y: int) -> None:
        self.x, self.y = x, y


def http_error(status: int) -> str:
    match status:
        case 400:
            return "Bad request"
        case 404:
            return "Not found"
        case 418 | 500 | 502:               # 或模式
            return "Server teapot / error"
        case _ if status < 400:             # 卫语句
            return "Informational"
        case _:
            return "Other"


def where_is(point: Point) -> str:
    match point:
        case Point(x=0, y=0):
            return "Origin"
        case Point(0, y=y):                 # 位置模式 + 部分捕获
            return f"Y-axis at {y}"
        case Point(x=x, y=0):
            return f"X-axis at {x}"
        case Point(x=x, y=y):
            return f"({x}, {y})"
        case _:
            return "Somewhere else"


def describe(data: Any) -> Any:
    match data:
        case {"type": "circle", "r": r} if r > 0:      # 映射模式 + guard
            return ("circle", r)
        case {"type": "rect", "w": w, **extra}:        # 映射模式 + **rest
            return ("rect", w, sorted(extra))
        case str() as s:                               # 类模式 + as 捕获
            return ("str", s)
        case []:
            return "empty sequence"
        case [1, 2, *rest]:                            # 序列模式 + 星号
            return ("starts-with-1-2", rest)
        case [Point(0, 0), *other_points]:              # 星号绑定剩余元素
            return ("on-y-axis", len(other_points))
        case (a, b):                                   # 元组模式（序列模式）
            return ("pair", a, b)
        case [x] | (x,) | {"k": x}:                    # 或模式跨三种形态
            return ("single", x)
        case None:                                     # 字面量 None
            return "None"
        case _:                                        # 通配
            return "fallback"


# 软关键字验证：match / case / _ 都还能当普通标识符用
match = 1
case = 2
_ = 3
soft_keyword_probe = (match, case, _)


def nested_match(cmd: str) -> str:
    match cmd.split():                                 # 序列模式匹配 token 列表
        case ["go", ("north" | "south" as dir_)]:      # 或模式 + as
            return f"go {dir_}"
        case ["go", ("east" | "west") as dir_]:
            return f"go {dir_}"
        case ["get", obj] | ["put", obj]:              # 或模式共享同一变量名
            return f"on {obj}"
        case ["quit" | "exit", *_]:
            return "bye"
        case _:
            return "unknown"


# =====================================================================
# 2. PEP 604 —— 联合类型 X | Y
#    注解里可直接写 int | str；运行时是 types.UnionType，
#    可以被 isinstance / issubclass 使用，也能和 typing.Union 比较。
# =====================================================================
def to_int(value: int | str | None) -> int:
    if value is None:
        raise ValueError("None")
    if isinstance(value, str):
        return int(value)
    return value


Json: TypeAlias = Union[int, str, bool, None]
NewJson: TypeAlias = int | str | bool | None
Nested: TypeAlias = list[int] | dict[str, "Nested"] | tuple["Nested", ...]

JsonValue = cast(Json, to_int)
maybe = cast(Optional[int], None)
union_type = int | str                    # types.UnionType 实例
same = (int | str) == Union[int, str]    # True
isinstance_ok = isinstance(3, int | str)
issubclass_ok = issubclass(bool, int | str)


def is_str_list(value: Any) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


# =====================================================================
# 3. PEP 612 —— 参数化注解 ParamSpec / Concatenate
#    签名保持装饰器终于有了官方类型写法（*args: P.args, **kwargs: P.kwargs）。
# =====================================================================
P = ParamSpec("P")
R = TypeVar("R")


def add_logging(fn: Callable[P, R]) -> Callable[P, R]:
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        print(f"[call] {fn.__name__}")
        return fn(*args, **kwargs)

    return wrapper


def with_prefix(
    prefix: str,
) -> Callable[[Callable[Concatenate[str, P], R]], Callable[P, R]]:
    """返回装饰器；Concatenate 表示被装饰函数要多收一个 prefix 参数。"""
    def decorator(fn: Callable[Concatenate[str, P], R]) -> Callable[P, R]:
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            head, *rest = args                 # Concatenate 的第一个 str 参数
            return fn(prefix + head, *rest, **kwargs)

        return wrapper

    return decorator


@add_logging
def mul(a: int, b: int, *, scale: int = 1) -> int:
    return a * b * scale


@with_prefix("py310:")
def banner(text: str, n: int = 1) -> str:
    return text + "!" * n


# =====================================================================
# 4. dataclasses —— KW_ONLY 哨兵 + slots=True（均为 3.10 新增）
# =====================================================================
@dataclass(slots=True)                    # 3.10：生成 __slots__ 版，省内存
class Config:
    name: str                            # 位置参数
    _: KW_ONLY                           # 3.10：其后字段强制关键字传递
    retries: int = 3
    timeout: float = 1.5
    tags: Tuple[str, ...] = ()


@dataclass
class Point3D:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def shifted(self, dx: float, dy: float) -> "Point3D":
        return Point3D(self.x + dx, self.y + dy, self.z)


# =====================================================================
# 5. PEP 618 —— 括号化 with 语句进一步放宽
#    3.9 已允许 `with (A() as a, B() as b):`；3.10 起尾随逗号、嵌套括号、
#    条目跨行书写都合法，且不再需要外层括号或反斜杠续行。
# =====================================================================
def write_pair(first: str, second: str) -> tuple[int, int]:
    tmp = Path(tempfile.gettempdir())
    a_path, b_path = tmp / "3.10_a.txt", tmp / "3.10_b.txt"
    with (
        a_path.open("w", encoding="utf-8") as fa,
        b_path.open("w", encoding="utf-8") as fb,
    ):
        fa.write(first)
        fb.write(second)
    return a_path.stat().st_size, b_path.stat().st_size


def guarded() -> str:
    with (
        contextlib.nullcontext(Path(tempfile.gettempdir())),   # 无 as 的纯 context manager
        contextlib.suppress(ZeroDivisionError),                # 与 as 并存，异常被吞掉
        contextlib.suppress(FileNotFoundError),
    ):
        1 / 0
    return "ZeroDivisionError suppressed"


async def closing_demo() -> str:
    async def agen() -> Any:
        try:
            yield 1
            yield 2
        finally:
            print("[aclosing] closing the async generator")

    async with contextlib.aclosing(agen()) as stream:      # 3.10 新增 aclosing
        first = await anext(stream)                         # 3.10 新内建 anext
    return f"aclosing closed after {first}"


# =====================================================================
# 6. 其余 3.10 标准库新增（非语法，同批发布）
# =====================================================================
# zip(strict=True)：长度不等直接 RuntimeError
paired = list(zip([1, 2, 3], "abc", strict=True))

# itertools.pairwise
windowed = list(itertools.pairwise([1, 2, 3, 4]))          # [(1,2),(2,3),(3,4)]

# int.bit_count / int.bit_length
bit_count, bit_length = 0b1011_0010.bit_count(), (255).bit_length()

# statistics.correlation
corr = statistics.correlation([1, 2, 3, 4], [2, 4, 5, 9])

# 3.10 新增内建：aiter / anext（异步迭代协议）
async def async_bits() -> tuple[str, str]:
    async def agen():
        yield 1
        yield 2

    it = aiter(agen())
    return str(await anext(it)), str([x async for x in it])


# =====================================================================
# 7. 3.10 移除（在这些代码里应当用新版写法）
#    collections.Iterable/Mapping/MutableMapping 等 ABC 别名已删；
#    parser 模块、parser.suite 已删（PEP 617 新解析器取代）；
#    @asyncio.coroutine 已删，用 async def。
# =====================================================================
from collections.abc import Iterable, Mapping, MutableMapping, Sequence  # noqa: E402

abc_aliases = (Iterable, Mapping, MutableMapping, Sequence)


# =====================================================================
# 附录 —— 基础语法总览（该版本仍然有效的全部语句 / 表达式形态）
# =====================================================================
class Mat:
    """只为演示 `@` 矩阵乘法运算符。"""

    def __init__(self, rows: list) -> None:
        self.rows = rows

    def __matmul__(self, other: "Mat") -> "Mat":
        return Mat([[sum(a * b for a, b in zip(row, col)) for col in other.rows]
                    for row in self.rows])

    def __repr__(self) -> str:
        return f"Mat({self.rows})"


def syntax_tour(literals: int, mapping: dict, seq: list, text: str) -> Any:
    global _tour_counter
    _tour_counter = 0

    # 数值字面量
    nums = (
        0,
        1_000_000,
        0xDEAD_BEEF,
        0o755,
        0b1010_1010,
        3.14,
        1e-3,
        6.02e23,
        .5,
        2. + 1j,
    )

    # 字符串：引号、前缀、隐式拼接、显式续行
    texts = (
        'single',
        "double",
        """triple
        multi""",
        "隐式" "拼接",
        "反斜杠\
续行",
        r"raw\no-escape",
        b"bytes\x00\xff",
        u"unicode 转义 é",
        rb"raw+bytes",
        f"{literals} 内嵌 {seq!r:>12}",
    )

    # 运算符与链式比较
    ops = (
        literals + 1 - 2 * 3 / 4 // 5 % 6 ** 7,
        literals << 1 | literals >> 1 & 0b11 ^ 0b01,
        ~literals,
        not literals or literals and True,
        -literals,
        0 < literals <= 10 != 5,
        literals if literals else -literals,
        Mat([[1, 2], [3, 4]]) @ Mat([[5, 6], [7, 8]]),   # 矩阵乘法运算符
        operator.index(literals),
    )

    # 容器字面量与解包
    lists = [literals, *seq, 1]
    tup = (literals, *seq, 2)
    sets = {literals, *seq, 3}
    dicts = {"a": literals, **{"b": 2}, "c": [3]}
    gen = {k: v for k, v in mapping.items() if k != "skip"}

    # 推导式：多个 for / 多个 if / 嵌套 / 异步
    comps = (
        [x for x in seq if x],
        [x * 2 for x in seq if x if x > 1],
        [(x, y) for x in seq for y in seq if x != y],
        {x for x in seq},
        {x: x for x in seq},
        tuple(x for x in seq),
        list(x for x in seq),
    )

    # 切片：普通 / 步长 / 省略 / 多维
    sl = (seq[1:2], seq[::2], seq[::-1], seq[-1:], seq[:-1:2],
          EllipsisBox()[...], EllipsisBox()[1:2], matrix[0][1:])

    # 海象运算符
    if (total := sum(x for x in seq if x)) > 0:
        _tour_counter = total

    # while / for + else + break / continue
    i = 0
    while i < 3:
        i += 1
    else:
        _tour_counter += 1
    for x in seq:
        if x == 1:
            continue
        break
    else:
        _tour_counter += 2

    # try / except / else / finally / raise from / 异常组语法见 PEP 654
    try:
        raise KeyError("k") from ValueError("v")
    except (KeyError, ValueError) as exc:
        _tour_counter += len(exc.args)
    except LookupError:
        pass
    else:
        _tour_counter += 100
    finally:
        _tour_counter += 1000

    # with / async with
    with contextlib.nullcontext(text) as ctx:
        _tour_counter += len(ctx)
    assert _tour_counter > -1, "counter must be positive"

    # 结构化模式匹配
    match literals:
        case int() | float():
            kind = "number"
        case _:
            kind = "other"

    # 生成器 / 协程语法
    def inner_gen(n: int = 3) -> Any:
        yield from range(n)
        got = yield n
        return got

    async def inner_coro(n: int) -> list:
        await asyncio.sleep(0)
        return [x async for x in inner_gen(n)]

    # del / lambda / 条件表达式 / 嵌套函数 / nonlocal / 装饰器
    def deco(fn):
        @wraps_like(fn)
        def wrapped(*a, **k):
            global _tour_counter
            _tour_counter += 1
            return fn(*a, **k)

        return wrapped

    @deco
    def decorated(a: int, /, b: int = 2, *args: int, c: int, d: int = 4, **kw: int) -> int:
        return a + b + sum(args) + c + d + sum(kw.values()) + operator.index(1)

    lam = lambda x=1, *, y=2: x + y if x else y
    acc = nonlocal_demo()
    result = [nums, texts, ops, lists, tup, sets, dicts, gen, comps, sl,
              kind, decorated(1, c=3), lam(), i, acc]
    del result[-1]
    return result


class EllipsisBox:
    """`x[...]` 只对自定义 `__getitem__` 生效（内建序列会 TypeError）。"""

    def __getitem__(self, key):
        if key is Ellipsis:
            return "Ellipsis 命中：返回自身"
        return key


matrix = [[1, 2], [3, 4]]


def nonlocal_demo() -> list:
    """nonlocal：内层函数改写外层函数的局部变量。"""
    total = 0

    def bump(step: int) -> None:
        nonlocal total
        total += step

    for i in range(3):
        bump(i)
    return [total]


def wraps_like(fn):
    """只保留 __wrapped__ 链的极简装饰器（functools.wraps 的最小子集）。"""
    def shim(decorated_fn):
        decorated_fn.__wrapped__ = fn
        return decorated_fn

    return shim


class Meta(type):
    """元类：class 头部的基类列表 + 元类参数。"""

    def __new__(mcls, name, bases, ns, **kwargs):
        ns["created_by"] = mcls.__name__
        return super().__new__(mcls, name, bases, ns)


class Base:
    def __init_subclass__(cls, *, tag: str = "", **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        cls.tag = tag


class Full(Base, metaclass=Meta):
    """类体：文档字符串、注解赋值、__slots__、各类方法、装饰器。"""

    __slots__ = ("value",)

    kind: str = "full"
    registry: dict[str, int] = {}

    def __init__(self, value: int = 0, *rest: int, key: str = "v", **kw: int) -> None:
        self.value = value
        self.registry[key] = value

    @property
    def doubled(self) -> int:
        return self.value * 2

    @doubled.setter
    def doubled(self, v: int) -> None:
        self.value = v // 2

    @staticmethod
    def unit() -> "Full":
        return Full(1)

    @classmethod
    def origin(cls) -> "Full":
        return cls(0)

    def __repr__(self) -> str:
        return f"Full({self.value!r})"

    async def fetch(self, n: int) -> list:
        await asyncio.sleep(0)
        return [x async for x in range(n)]

    def gen(self):
        yield from self.value


async def _run_async() -> tuple:
    return await async_bits(), await closing_demo()


def main() -> None:
    loop = asyncio.new_event_loop()
    try:
        bits, closing = loop.run_until_complete(_run_async())
    finally:
        loop.close()
    demo = {
        "PEP634 字面量/或模式": (http_error(400), http_error(418), http_error(100)),
        "PEP634 类模式": (where_is(Point(0, 0)), where_is(Point(0, 3)), where_is(Point(1, 2))),
        "PEP634 映射/序列": (
            describe({"type": "circle", "r": 2}),
            describe({"type": "rect", "w": 1, "h": 2}),
            describe([1, 2, 7, 8]),
            describe((Point(0, 0), Point(0, 0))),
            describe("hi"),
            describe([9]),
            describe(None),
        ),
        "PEP634 嵌套/软关键字": (nested_match("go north"), nested_match("exit now"), soft_keyword_probe),
        "PEP604 联合类型": (to_int("42"), union_type, same, isinstance_ok, issubclass_ok),
        "TypeAlias/TypeGuard": (NewJson, Nested, JsonValue, is_str_list(["a"])),
        "PEP612 ParamSpec": (mul(2, 3, scale=4), banner("ok", 2)),
        "KW_ONLY + slots": (Config("c", retries=1), Config.__slots__, dataclasses.asdict(Point3D(1, 2))),
        "PEP618 括号化 with": (write_pair("a", "bb"), guarded(), closing),
        "zip strict / pairwise": (paired, windowed),
        "bit_count / corr": (bit_count, bit_length, corr),
        "3.10 新内建 aiter/anext": bits,
        "collections.abc 新家": abc_aliases,
    }
    for key, value in demo.items():
        print(f"{key:<24} -> {value}")
    print("syntax_tour              ->", len(syntax_tour(3, {"a": 1}, [1, 2, 3], "hi")))
    print("Full/Base                ->", Full.origin(), Full.unit(), Full(2).doubled, Full.tag)


if __name__ == "__main__":
    main()