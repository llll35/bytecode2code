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
    raise RuntimeError("本文件需要 Python 3.9 或更高版本")


# =====================================================================
# 1. PEP 585 —— 内置容器 / 抽象基类支持下标（即 PEP 585 泛型别名）
#    3.9 起 list[int]、dict[str, int]、collections.abc.Callable[...] 合法，
#    返回 types.GenericAlias；typing.List / typing.Dict 等已废弃。
#    注意：PEP 612 的 ParamSpec / Concatenate 要到 3.10 才有。
# =====================================================================
T = TypeVar("T")
R = TypeVar("R")

int_list: list[int] = [1, 2, 3]
pair: dict[str, tuple[int, ...]] = {"a": (1, 2)}
frozen: frozenset[str] = frozenset({"x"})
the_type: type[int] = int
cb: Callable[[int, str], bool] = lambda i, s: bool(i) and bool(s)
seq: Sequence[int] = [1, 2]            # collections.abc.* 同样支持下标
alias = list[int]           # types.GenericAlias 实例
origin = alias.__origin__   # list
args = alias.__args__       # (int,)


class Stack(Generic[T]):
    """PEP 585 + PEP 612 的普通泛型类写法（3.9 起可写 list[T]）"""

    def __init__(self) -> None:
        self._items: list[T] = []

    def push(self, item: T) -> None:
        self._items.append(item)

    def pop(self) -> T:
        return self._items.pop()

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)


class IntList(list[int]):     # 3.9 起可以直接继承泛型别名
    pass


# =====================================================================
# 2. PEP 593 —— typing.Annotated：给类型附加元数据
#    3.9 起 get_type_hints(..., include_extras=True) 可取回 Annotated。
# =====================================================================
Port = Annotated[int, "TCP/UDP 端口", 0]
StrictStr = Annotated[str, "禁止为空"]
WriteMode = Literal["w", "a", "x", "r+"]
MAX_CONNECTIONS: Final = 512


# =====================================================================
# 3. PEP 614 —— 装饰器不再局限于 @name，可以是任意表达式
#    3.8 只允许 @name 或 @name.attr，3.9 允许下标、调用、lambda、括号等。
# =====================================================================
class Registry:
    def __init__(self, event: str) -> None:
        self.event = event
        self.handlers: list[Callable[[], None]] = []

    def on(self, phase: str) -> Callable[[Callable[[], None]], Callable[[], None]]:
        def decorator(fn: Callable[[], None]) -> Callable[[], None]:
            self.handlers.append(fn)
            return fn

        return decorator

    def __call__(self, fn: Callable[[], None]) -> Callable[[], None]:
        return fn


EVENTS: list[Registry] = [Registry("click"), Registry("scroll")]


@EVENTS[0].on("pressed")      # 任意表达式：下标 + 属性链 + 调用
def on_pressed() -> None:
    print("pressed")


@(lambda fn: fn)              # 任意表达式：lambda
def identity() -> None:
    print("identity")


@EVENTS[1].on("phase")        # PEP 614 新语法 + PEP 585 泛型注解
def handler() -> None:
    print("scroll phase")


F = TypeVar("F", bound=Callable[..., object])


def with_extra_logging(fn: F) -> F:
    """3.9 里用 bound=Callable 的 TypeVar 做签名保持装饰器；
    PEP 612 的 ParamSpec 写法（fn: Callable[P, R] / *args: P.args）
    要到 Python 3.10 才可用。"""
    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        return fn(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


@with_extra_logging
def compute(a: int, b: int = 2) -> int:
    return a * b


# =====================================================================
# 4. PEP 584 —— dict 联合运算符 | 与 |=（右侧优先）
# =====================================================================
base = {"id": 1, "name": "ada", "deprecated": True}
extra = {"name": "grace", "year": 1815}
merged = base | extra                 # {'id':1,'name':'grace','deprecated':True,'year':1815}
merged_overwrites = {**base, **extra}  # 等价于 base | extra
base |= {"extra_flag": True}          # 原地 union（dict |= mapping，3.9+）
frozen_map = {}.fromkeys(["a", "b"], 0)
from_zip = dict(zip(int_list, pair["a"]))


# =====================================================================
# 5. str.removeprefix / str.removesuffix
# =====================================================================
module = "package.module"
short = module.removeprefix("package.")           # "module"
doc_name = "report.final.pdf"
stem = doc_name.removesuffix(".pdf")               # "report.final"
no_change = "".removeprefix("x")                   # "" （不会抛异常）


# =====================================================================
# 6. PEP 617 —— 新的 PEG 解析器语法：括号化的多上下文管理器
#    3.9 起 `with (A() as a, B() as b):` 合法（原来必须靠反斜杠续行），
#    且允许把 with 拆成多行（3.10 前只能用一条语句里的括号）。
# =====================================================================
def write_pair(first: str, second: str) -> tuple[int, int]:
    tmp = Path(tempfile.gettempdir())
    a_path, b_path = tmp / "3.9_a.txt", tmp / "3.9_b.txt"
    with (
        a_path.open("w", encoding="utf-8") as fa,
        b_path.open("w", encoding="utf-8") as fb,
    ):
        fa.write(first)
        fb.write(second)
    return a_path.stat().st_size, b_path.stat().st_size


def guarded() -> str:
    with (
        Path(tempfile.gettempdir()),          # 无 as 的纯 context manager
        suppress(ZeroDivisionError),           # 与 as 并存，异常被吞掉
    ):
        1 / 0
    return "ZeroDivisionError 已被 suppress"


# =====================================================================
# 7. 其余 3.9 新增标准库能力（非语法，但同批发布）
# =====================================================================
@functools.cache                       # 3.9：等价于 lru_cache(maxsize=None)
def fib(n: int) -> int:
    return n if n < 2 else fib(n - 1) + fib(n - 2)


# 3.9：ast.unparse —— 由 AST 反向生成源码
def unparse_demo() -> str:
    tree = ast.parse("x: list[int] = [i for i in range(10) if i % 2]")
    return ast.unparse(tree)


# 3.9：zoneinfo（IANA 时区；Windows 需 tzdata，无数据时回退）
def now_in_tz() -> datetime:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        tz = ZoneInfo("Asia/Shanghai")
    except ZoneInfoNotFoundError:
        from datetime import timezone

        tz = timezone(8 * 3600, "CST")
    return datetime.now(tz)


# 3.9：graphlib.TopologicalSorter —— 拓扑排序
def topo() -> list[str]:
    from graphlib import TopologicalSorter

    graph = {"app": ["db", "cache"], "db": [], "cache": ["db"]}
    ts = TopologicalSorter(graph)
    return list(ts.static_order())


# 3.9：math.lcm / math.nextafter / math.ulp
def math_bits() -> tuple[int, float, float]:
    return math.lcm(4, 6, 10), math.nextafter(1.0, 2.0), math.ulp(1e-3)


# 3.9 移除：typing.Text、collections.Iterable/Mapping 等别名、parser 模块、sys.last_traceback
extra_metadata = get_type_hints(write_pair, include_extras=True)


def main() -> None:
    stack: Stack[int] = Stack()
    for n in (1, 2, 3):
        stack.push(n)
    demo = {
        "PEP585 泛型别名": (alias, origin, args, the_type, IntList, seq),
        "泛型类 Stack": (stack.pop(), list(Stack[int]())),
        "签名保持装饰器": compute(3, 4),
        "PEP614 装饰器": (on_pressed, identity, handler),
        "PEP593 Annotated": (Port, StrictStr, WriteMode, MAX_CONNECTIONS, extra_metadata),
        "PEP584 dict 联合": (merged, merged_overwrites, base),
        "removeprefix/suffix": (short, stem, no_change),
        "PEP617 括号化 with": (write_pair("a", "bb"), guarded()),
        "functools.cache": fib(30),
        "ast.unparse": unparse_demo(),
        "zoneinfo": now_in_tz().isoformat(),
        "graphlib": topo(),
        "math 3.9": math_bits(),
        "fromkeys/zip": (frozen_map, from_zip),
    }
    for key, value in demo.items():
        print(f"{key:<20} -> {value}")


if __name__ == "__main__":
    main()
