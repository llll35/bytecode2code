"""
Python 3.12 全部新增语法 / 关键特性演示。
运行要求：CPython 3.12+
在 3.11 上会抛 SyntaxError（PEP 695 类型参数语法、PEP 701 f-string 是本版本新语法）
或 AttributeError（itertools.batched、math.sumprod、enum.verify 等运行时能力）。
"""
from __future__ import annotations

import asyncio
import contextlib
import enum
import itertools
import math
import operator
import os
import re
import sys
import tempfile
import types
from collections.abc import Callable
from pathlib import Path
from typing import (
    Any,
    NoReturn,
    TypedDict,
    TypeAliasType,
    Unpack,
    override,
)

if sys.version_info < (3, 12):
    raise RuntimeError("本文件需要 Python 3.12 或更高版本")


# =====================================================================
# 1. PEP 695 —— 类型参数新语法（本版本最重要的新语法）
#    * `type Alias[T] = ...`        类型别名语句，泛型别名不再需要 TypeVar + Generic
#    * `def f[T](x: T) -> T`        函数类型参数
#    * `class C[T]: ...`            类类型参数
#    * 类型参数支持边界 `T: int`、约束 `T: (int, str)`
#    * 支持 `*Ts`（TypeVarTuple）与 `**P`（ParamSpec）
#    * 注解改为惰性求值，不再需要字符串前向引用 / TypeVar 上界排序
#    * `type` 是软关键字：变量名仍可叫 type
# =====================================================================
type UserId = int
type Handler[**P, R] = Callable[P, R]                # ParamSpec 版别名
type Matrix = list[list[UserId]]
type Pair[T] = tuple[T, T]                         # 泛型类型别名
type Json = dict[str, "Json | list[Json] | int"]   # 自引用别名（惰性求值，不用写字符串）


def first_item[T](items: list[T]) -> T:            # 函数类型参数
    return items[0]


def clamp[T: int](value: T, low: T, high: T) -> T: # 边界（bound）
    return max(low, min(value, high))


def coerce[T: (int, str)](value: T | bytes) -> T:  # 约束（constraints）
    if isinstance(value, bytes):
        return int(value)                           # type: ignore[return-value]
    return value


class Stack[T]:                                    # 类类型参数
    def __init__(self) -> None:
        self._items: list[T] = []

    def push(self, item: T) -> "Stack[T]":
        self._items.append(item)
        return self

    def pop(self) -> T:
        return self._items.pop()

    def __repr__(self) -> str:
        return f"Stack({self._items!r})"


def manual_type_alias() -> Any:
    """不写 `type` 语句时，3.12 新增的 TypeAliasType 是等价的手写版本。"""
    PairAlias = TypeAliasType("PairAlias", tuple)     # 运行时对象
    return PairAlias, PairAlias.__name__


class Tensor[T]:                                  # 类类型参数，名字可以随便取
    def __init__(self, *rows: T) -> None:
        self.rows = rows

    def first_row(self) -> tuple[T, ...]:
        return self.rows[0] if self.rows else ()


class Pairs[*Ts]:                                 # 3.11 的 TypeVarTuple 也能用新语法写
    def __init__(self, *values: *Ts) -> None:
        self.values = values


def concat[*Ts](*values: *Ts) -> tuple[*Ts]:
    return values


def apply[**P, R](fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    return fn(*args, **kwargs)


class Callbacks[**P]:
    def __init__(self, fn: Callable[P, Any]) -> None:
        self.fn = fn

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        return self.fn(*args, **kwargs)


def type_is_soft_keyword() -> str:
    """`type` 是软关键字：变量名、函数名照旧能用。"""
    type = "3.12"
    return type


soft_keyword_probe = type_is_soft_keyword()


# =====================================================================
# 2. PEP 701 —— f-string 正式“解禁”
#    * 表达式部分可以复用引号：f"{"hi"}"、f"{d["k"]}"
#    * 表达式部分可以含反斜杠
#    * 三引号 f-string 可以跨行，且可以写注释
#    * 嵌套同引号 f-string 合法
# =====================================================================
def fstring_demo(mapping: dict, width: int, parts: list[str]) -> dict:
    return {
        "复用双引号": f"{"hi"}",
        "复用单引号": f"{'hi'}",
        "同引号嵌套字典": f"{mapping["key"]}",
        "同引号嵌套下标": f"{parts[0]}",
        "反斜杠换行": f"{'\n'.join(parts)}",
        "内嵌 f-string": f"{f"{width:>6}"}",
        "调试等号": f"{width=}",
        "转换与格式": f"{width!r:>{width}}",
        "多行带注释": f"""
            width = {width}
            # 这里是注释，3.12 起合法
            upper = {width!r:>{width}}
        """,
        "嵌套多行": f"""
            outer = {f"""
                inner = {width}
            """}
        """,
    }


# =====================================================================
# 3. PEP 692 —— Unpack[TypedDict] 用在 **kwargs 上
# =====================================================================
class Movie(TypedDict):
    name: str
    year: int


def render_movie(**movie: Unpack[Movie]) -> str:
    """`render_movie(name=..., year=...)` 才能通过类型检查。"""
    return f"{movie['name']} ({movie['year']})"


class Flags(TypedDict):
    verbose: bool
    color: str


def parse_flags(**flags: Unpack[Flags]) -> tuple:
    return flags["verbose"], flags["color"]


# =====================================================================
# 4. PEP 698 —— @override：显式标注“这里是覆盖父类实现”
# =====================================================================
class BaseReader:
    def read(self, path: str) -> str:
        return ""

    def close(self) -> None:
        pass


class FileReader(BaseReader):
    @override                               # 覆盖 read
    def read(self, path: str) -> str:
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def close(self) -> None:                # 没有 @override，也不影响运行
        pass


# =====================================================================
# 5. PEP 709 —— 列表/集合/字典推导式与生成器表达式被内联进外层函数
#    不再为每个推导式单独创建 code object，因此也不再单独占一帧。
# =====================================================================
def comprehension_demo(n: int) -> tuple:
    squares = [x * x for x in range(n)]
    cubes = {x ** 3 for x in range(n)}
    table = {x: x * 2 for x in range(n)}
    total = sum(x for x in range(n))               # 生成器表达式仍不内联
    return squares, cubes, table, total


def only_comprehensions(n: int) -> tuple:
    return ([x for x in range(n)],
            {x for x in range(n)},
            {x: x for x in range(n)})


def nested_code_objects(fn) -> tuple:
    """3.12 起列表/集合/字典推导式被内联进函数体，co_consts 里不再出现它们。"""
    return tuple(c for c in fn.__code__.co_consts if isinstance(c, types.CodeType))


# =====================================================================
# 6. 3.12 标准库新增：itertools.batched / math.sumprod / pathlib.Path.walk /
#    enum.EnumCheck + verify / typing.TypeAliasType / asyncio.eager_task_factory /
#    sys.monitoring / re 的 \N{...}
# =====================================================================
# itertools.batched：按固定长度切块，最后一块可能短
batches = list(itertools.batched([1, 2, 3, 4, 5], 2))          # [(1,2),(3,4),(5,)]

# math.sumprod：sum(a*b for a, b in zip(p, q))，精度更高
sumprod = math.sumprod([1, 2, 3], [4, 5, 6])                   # 32

# pathlib.Path.walk：自底向上遍历目录树
def walk_demo() -> list:
    found: list[str] = []
    with contextlib.suppress(OSError):
        for root, dirs, files in Path(tempfile.gettempdir()).walk():
            found.append(os.path.basename(root))
            if len(found) >= 3:
                break
    return found


# enum.EnumCheck + enum.verify：可校验成员唯一性 / 连续性 / 命名 flag
@enum.verify(enum.EnumCheck.UNIQUE)
class Verified(enum.Enum):
    A = 1
    B = 2
    C = 3


enum_error = None
try:
    @enum.verify(enum.EnumCheck.UNIQUE)
    class Duplicated(enum.Enum):                    # B 是 A 的别名，违反 UNIQUE
        A = 1
        B = 1
except ValueError as exc:
    enum_error = str(exc)


# re 模块：支持 \N{名字}
alpha = re.match(r"\N{GREEK SMALL LETTER ALPHA}", "α") is not None

# asyncio.eager_task_factory：协程第一次 await 之前就同步执行
async def eager_demo() -> list:
    order: list[str] = []

    async def coro(tag: str) -> str:
        order.append(f"start {tag}")
        await asyncio.sleep(0)
        order.append(f"end {tag}")
        return tag

    loop = asyncio.get_running_loop()
    old = loop.get_task_factory()
    loop.set_task_factory(asyncio.eager_task_factory)
    try:
        results = await asyncio.gather(coro("a"), coro("b"))
    finally:
        loop.set_task_factory(old)
    return [results, order]


# sys.monitoring：PEP 669 低层监控 API（替代 sys.setprofile / sys.settrace）
class Counter:
    def __init__(self) -> None:
        self.starts = 0

    def __call__(self, code: types.CodeType, offset: int) -> None:
        self.starts += 1


def monitoring_demo() -> int:
    mon = sys.monitoring
    tool_id = mon.PROFILER_ID          # 官方保留的工具位，本 demo 只借用
    counter = Counter()
    mon.use_tool_id(tool_id, "syntax-demo")
    try:
        mon.register_callback(tool_id, mon.events.PY_START, counter)
        mon.set_events(tool_id, mon.events.PY_START)
        try:
            comprehension_demo(2)
        finally:
            mon.set_events(tool_id, mon.events.NO_EVENTS)
            mon.register_callback(tool_id, mon.events.PY_START, None)
    finally:
        mon.free_tool_id(tool_id)
    return counter.starts


# =====================================================================
# 7. 3.12 移除
#    distutils、asynchat、asyncore、smtpd、imp、aifc/audioop/cgi/chunk/cmath/
#    crypt/imghdr/mailcap/msilib/nis/nntplib/ossaudiodev/pipes/sndhdr/spwd/
#    sunau/telnetlib/uu/xdrlib 等“死电池”，以及 unittest 的旧式别名方法
#    （failUnless / assertEquals / ...）、locale.resetlocale()。
# =====================================================================
def no_removed_modules() -> str:
    return "distutils / asyncore / smtpd / imp / cgi / telnetlib ... 已移除"


# =====================================================================
# 附录 —— 基础语法总览（该版本仍然有效的全部语句 / 表达式形态）
# =====================================================================
def syntax_tour(literals: int, mapping: dict, seq: list, text: str) -> Any:
    global _tour_counter
    _tour_counter = 0

    nums = (
        0, 1_000_000, 0xDEAD_BEEF, 0o755, 0b1010_1010,
        3.14, 1e-3, 6.02e23, .5, 2. + 1j,
    )
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
    ops = (
        literals + 1 - 2 * 3 / 4 // 5 % 6 ** 7,
        literals << 1 | literals >> 1 & 0b11 ^ 0b01,
        ~literals,
        not literals or literals and True,
        -literals,
        0 < literals <= 10 != 5,
        literals if literals else -literals,
        operator.index(literals),
    )
    lists = [literals, *seq, 1]
    tup = (literals, *seq, 2)
    sets = {literals, *seq, 3}
    dicts = {"a": literals, **{"b": 2}, "c": [3]}
    gen = {k: v for k, v in mapping.items() if k != "skip"}
    comps = (
        [x for x in seq if x],
        [x * 2 for x in seq if x if x > 1],
        [(x, y) for x in seq for y in seq if x != y],
        {x for x in seq},
        {x: x for x in seq},
        tuple(x for x in seq),
        list(x for x in seq),
    )
    sl = (seq[1:2], seq[::2], seq[::-1], seq[-1:], seq[:-1:2],
          EllipsisBox()[...], EllipsisBox()[1:2])

    if (total := sum(x for x in seq if x)) > 0:
        _tour_counter = total

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

    try:
        raise ExceptionGroup("group", [ValueError("a"), TypeError("b")])
    except* ValueError as eg:
        _tour_counter += len(eg.exceptions)
    except* TypeError as eg:
        _tour_counter += len(eg.exceptions)
    finally:
        _tour_counter += 10000

    with contextlib.nullcontext(text) as ctx:
        _tour_counter += len(ctx)
    assert _tour_counter > -1, "counter must be positive"

    match literals:                                   # 3.10 引入
        case int() | float():
            kind = "number"
        case _:
            kind = "other"

    def inner_gen(n: int = 3) -> Any:
        yield from range(n)
        got = yield n
        return got

    async def inner_coro(n: int) -> list:
        await asyncio.sleep(0)
        return [x async for x in inner_gen(n)]

    def deco(fn):
        @wraps_like(fn)
        def wrapped(*a, **k):
            global _tour_counter
            _tour_counter += 1
            return fn(*a, **k)

        return wrapped

    @deco
    def decorated(a: int, /, b: int = 2, *args: int, c: int, d: int = 4, **kw: int) -> int:
        return a + b + sum(args) + c + d + sum(kw.values())

    lam = lambda x=1, *, y=2: x + y if x else y
    acc = nonlocal_demo()
    result = [nums, texts, ops, lists, tup, sets, dicts, gen, comps, sl,
              kind, decorated(1, c=3), lam(), i, acc]
    del result[-1]
    return result


def wraps_like(fn):
    def shim(decorated_fn):
        decorated_fn.__wrapped__ = fn
        return decorated_fn

    return shim


def nonlocal_demo() -> list:
    total = 0

    def bump(step: int) -> None:
        nonlocal total
        total += step

    for i in range(3):
        bump(i)
    return [total]


def never() -> NoReturn:
    raise RuntimeError("never")


class EllipsisBox:
    def __getitem__(self, key):
        if key is Ellipsis:
            return "Ellipsis 命中：返回自身"
        return key


class Meta(type):
    def __new__(mcls, name, bases, ns, **kwargs):
        ns["created_by"] = mcls.__name__
        return super().__new__(mcls, name, bases, ns)


class Base:
    def __init_subclass__(cls, *, tag: str = "", **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        cls.tag = tag


class Full(Base, metaclass=Meta):
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


def main() -> None:
    loop = asyncio.new_event_loop()
    try:
        eager = loop.run_until_complete(eager_demo())
    finally:
        loop.close()

    stack: Stack[int] = Stack()
    demo = {
        "PEP695 函数类型参数": (first_item([1, 2]), clamp(9, 0, 5), coerce(b"7")),
        "PEP695 类类型参数": (
            repr(stack.push(1).push(2)),
            repr(Tensor(1, 2)),
            Stack.__type_params__,
            Tensor.__type_params__,
        ),
        "PEP695 类型别名": (Pair[int], Pair[int] | None, UserId, Matrix, Json, Handler),
        "PEP695 可变长/ParamSpec": (concat(1, "a"), Pairs(1, 2).values,
                          apply(lambda a, b=0: a + b, 1, b=2),
                          Callbacks(lambda a, b=0: a + b)(1, b=2)),
        "TypeAliasType 手写版": manual_type_alias(),
        "PEP701 f-string": fstring_demo({"key": "value"}, 8, ["a", "b"]),
        "PEP692 Unpack kwargs": (render_movie(name="Up", year=1996),
                        parse_flags(verbose=True, color="red")),
        "PEP698 @override": FileReader.__dict__["read"].__qualname__,
        "PEP709 推导式内联": (comprehension_demo(4),
                             nested_code_objects(only_comprehensions),
                             nested_code_objects(comprehension_demo)),
        "itertools.batched": batches,
        "math.sumprod": sumprod,
        "pathlib.Path.walk": walk_demo(),
        "enum verify": (Verified.A, enum_error),
        "re \\N{}": alpha,
        "asyncio.eager_task_factory": eager,
        "sys.monitoring": monitoring_demo(),
        "3.12 移除": no_removed_modules(),
        "type 软关键字": soft_keyword_probe,
    }
    for key, value in demo.items():
        print(f"{key:<28} -> {value}")
    print("syntax_tour               ->", len(syntax_tour(3, {"a": 1}, [1, 2, 3], "hi")))
    print("Full/Base                 ->", Full.origin(), Full.unit(), Full(2).doubled, Full.tag)


if __name__ == "__main__":
    main()