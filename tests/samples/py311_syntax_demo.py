"""
Python 3.11 全部新增语法 / 关键特性演示。
运行要求：CPython 3.11+
在 3.10 上会抛 SyntaxError（`except*` 是本版本新语法）或 NameError / AttributeError
（ExceptionGroup、Self、TypeVarTuple、tomllib 等运行时能力）。
"""
from __future__ import annotations

import asyncio
import contextlib
import enum
import datetime
import enum
import hashlib
import inspect
import io
import operator
import sys
import tomllib
import traceback
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    LiteralString,
    Never,
    NoReturn,
    NotRequired,
    Required,
    Self,
    TypedDict,
    TypeVarTuple,
    Unpack,
    assert_never,
    assert_type,
    dataclass_transform,
    reveal_type,
)

if sys.version_info < (3, 11):
    raise RuntimeError("本文件需要 Python 3.11 或更高版本")


# =====================================================================
# 1. PEP 654 —— ExceptionGroup 与 `except*` 语法（本版本最重要的新语法）
#    * 一个 except* 子句按类型拆开异常组里匹配的异常，抓到的名字是 ExceptionGroup；
#    * 未匹配的异常继续往后传播，最终未被处理的合并成一个 ExceptionGroup 抛出；
#    * 规则：不能同时出现裸 `except`，不能和 `except` 混写，不能有 `else`，可以有 `finally`。
# =====================================================================
def parse_batch(payloads: dict) -> dict:
    result: dict = {}
    allowed = {"a", "b"}
    errors: list[Exception] = []
    try:
        for key, raw in payloads.items():
            try:
                if key not in allowed:
                    raise KeyError(key)
                result[key] = int(raw)
            except (KeyError, ValueError) as exc:
                errors.append(exc)                 # 先攒起来
        if errors:
            raise ExceptionGroup("批量解析失败", errors)
    except* ValueError as eg:                      # 一次拆出所有 ValueError
        print("bad ints:", [str(e) for e in eg.exceptions])
    except* KeyError as eg:                        # 另一个 except* 子句
        print("bad keys:", [str(e) for e in eg.exceptions])
    finally:
        print("[parse_batch] done")
    return result


def parse_batch_ok(payloads: dict) -> dict:
    """except* 里不处理就原样 raise，异常组继续向上传播。"""
    try:
        return {k: int(v) for k, v in payloads.items()}
    except* ValueError:
        raise
    finally:
        print("[parse_batch_ok] done")


def build_group() -> ExceptionGroup:
    """手动构造异常组。"""
    eg = ExceptionGroup(
        "多个子系统同时失败",
        [ValueError("v"), TypeError("t"), KeyError("k")],
    )
    return eg


def split_group(eg: ExceptionGroup) -> tuple:
    """split() 把组拆成 (匹配到的组, 剩下的组)；subgroup() 只挑某几类异常。"""
    matched, rest = eg.split(KeyError)
    subgroup = rest.subgroup(TypeError)              # 只留 TypeError
    rebuilt = ExceptionGroup("重建的组", list(subgroup.exceptions))
    return matched, rest, subgroup, rebuilt


async def task_group_demo() -> list:
    """asyncio.TaskGroup：任一子任务失败就取消其余并抛出 ExceptionGroup。"""
    done: list[str] = []

    async def work(n: int) -> None:
        await asyncio.sleep(0)
        if n == 2:
            raise ValueError(f"task {n} failed")
        done.append(f"task {n}")

    try:
        async with asyncio.TaskGroup() as tg:         # 3.11
            for n in range(4):
                tg.create_task(work(n))
    except* ValueError as eg:
        done.append(f"caught {len(eg.exceptions)} ValueError")
    return done


# =====================================================================
# 2. PEP 678 —— 异常注解 add_note()，traceback 末尾会原样打印这些 note
# =====================================================================
class HttpError(Exception):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status}")
        self.status, self.url = status, url

    def with_notes(self, *notes: str) -> "HttpError":
        for note in notes:                            # 逐条挂 note
            self.add_note(note)
        return self


def noteless_traceback() -> str:
    try:
        raise HttpError(404, "/missing").with_notes("request-id=abc", "retry budget left: 2")
    except HttpError as exc:
        return f"{exc!r} notes={exc.__notes__}"


# =====================================================================
# 3. PEP 646 —— 可变长泛型 TypeVarTuple / Unpack
#    写法：`*Ts`、`Generic[*Ts]`、`*args: Unpack[Ts]`、`tuple[*Ts]`、`*Ts` 解包。
# =====================================================================
Shape = TypeVarTuple("Shape")


class Array(Generic[*Shape]):
    """一个形状由任意多个 int 组成的数组。"""

    def __init__(self, *shape: Unpack[Shape]) -> None:
        self.shape = shape                            # tuple[int, ...]

    def __repr__(self) -> str:
        return f"Array{self.shape}"

    def first(self) -> Any:
        return self.shape[0]


def make_array(*shape: Unpack[Shape]) -> Array[*Shape]:
    return Array(*shape)


def pass_through(*args: Unpack[Shape]) -> tuple[*Shape]:
    """可变长参数原样转发，tuple[*Ts] 表示长度与入参一致。"""
    return args


def apply_all(fns: list, *args: Unpack[Shape]) -> tuple:
    return tuple(f(*args) for f in fns)


# 3.11：Unpack 也能用在 TypedDict 上做嵌套
class Point2D(TypedDict):
    x: int
    y: int


class Point3DExtras(TypedDict):
    z: Required[int]
    label: NotRequired[str]


class Nested(TypedDict):
    origin: Point2D
    extra: Unpack[Point3DExtras]


# =====================================================================
# 4. PEP 673 —— Self：方法返回自身类型，子类自动得到子类型
# =====================================================================
class Shape2D:
    def __init__(self, w: float = 1.0, h: float = 1.0) -> None:
        self.w, self.h = w, h

    def with_size(self, w: float, h: float) -> Self:
        return type(self)(w, h)                       # 返回自身类型而非基类

    def scaled(self, k: float) -> Self:
        new = self.with_size(self.w * k, self.h * k)
        assert_type(new, Self)
        return new


class Square(Shape2D):
    def __init__(self, side: float = 1.0) -> None:
        super().__init__(side, side)

    def with_size(self, w: float, h: float) -> Self:
        return type(self)(max(w, h))                  # Self 让子类覆写也保持返回类型

    def clone(self) -> Self:
        return type(self)(self.w)                     # Self 帮我们省掉 cast


# =====================================================================
# 5. PEP 675 —— LiteralString：只接受“字面量拼出来的”字符串
# =====================================================================
def query(table: LiteralString, column: LiteralString) -> str:
    return f"SELECT {column} FROM {table}"


def literal_string_demo() -> tuple:
    ok = query("users", "name")
    dynamic = "".join(["us", "ers"])
    not_literal = query(dynamic, "name")             # 类型检查器会报错
    return ok, not_literal


# =====================================================================
# 6. PEP 655 —— @dataclass_transform：让库作者声明“类工厂等价于 dataclass”
# =====================================================================
@dataclass_transform(field_specifiers=(int, float, str))
def define(cls: type = None, /, **fields: Any) -> Any:
    """假装这是一个 dataclass 等价物：既可裸用 `@define`，也可 `@define(x=1)`。"""
    if cls is None:
        return lambda klass: define(klass, **fields)

    def __init__(self: Any, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

    for k, v in fields.items():
        setattr(cls, k, v)
    cls.__init__ = __init__                            # type: ignore[attr-defined]
    cls.__annotations__ = {k: type(v) for k, v in fields.items()}
    return cls


@define
class PlainModel:
    """裸用：等价于 @dataclass。"""


@define(x=1, y="two")
class PointModel:
    """带参数用：等价于 @dataclass(x=1, y="two")。"""


# =====================================================================
# 7. typing 其它新增：Never / assert_never / assert_type / reveal_type / Variadic
# =====================================================================
def describe(value: int | str) -> NoReturn | str:
    match value:
        case int():
            return f"int {value}"
        case str():
            return f"str {value!r}"
        case _:
            assert_never(value)                       # 静态穷尽检查，运行时抛错


def never_return() -> Never:
    raise RuntimeError("永远不到这里")


if TYPE_CHECKING:
    reveal_type(describe(1))                          # 只给类型检查器看


# =====================================================================
# 8. enum：StrEnum / ReprEnum / _missing_ / Flag 的 boundary / enum.property
# =====================================================================
class Color(enum.StrEnum):                             # 3.11
    RED = "red"
    GREEN = "green"


class Mode(int, enum.ReprEnum):                       # 3.11：repr 保留成员名
    FAST = 1
    SLOW = 2


class Level(enum.IntEnum):
    LOW = 10
    MID = 20
    HIGH = 30

    @classmethod
    def _missing_(cls, value: object) -> "Level | None":
        if isinstance(value, str):                    # 3.11 起 _missing_ 返回成员
            return cls[value.upper()]
        return None


class Bits(enum.IntFlag, boundary=enum.KEEP):          # 3.11 新增 KEEP
    READ = 1
    WRITE = 2
    EXEC = 4


class Temperature(enum.Enum):
    HOT = enum.auto()
    WARM = enum.auto()

    @enum.property                                  # 3.11 新增：不会和成员名打架的 property
    def celsius(self) -> str:
        return f"{self.name}={self.value}"


# =====================================================================
# 9. 3.11 标准库新增：asyncio Runner/timeout、contextlib.chdir、tomllib、
#    math.exponent、sys.exception()、int<->str 位数限制
# =====================================================================
async def timeout_demo() -> str:
    try:
        async with asyncio.timeout(0.001):            # 3.11
            await asyncio.sleep(1)
    except TimeoutError:
        return "asyncio.timeout fired"
    return "no timeout"


def runner_demo() -> Any:
    async def quick() -> str:
        await asyncio.sleep(0)
        return "runner ok"

    with asyncio.Runner() as runner:                  # 3.11
        return runner.run(quick())


def chdir_demo(path: str) -> str:
    import os

    previous = os.getcwd()
    with contextlib.chdir(path):                      # 3.11：自动还原 cwd
        inner = os.path.basename(os.getcwd())
    return f"{inner} -> restored={previous == os.getcwd()}"


def toml_demo() -> dict:
    doc = b"""
[tool.demo]
name = "bytecode2code"
targets = ["3.10", "3.11", "3.12"]
"""
    return tomllib.loads(doc.decode("utf-8"))         # 3.11 新增 tomllib


def sys_exception_demo() -> str:
    try:
        raise KeyError("k")
    except KeyError:
        current = sys.exception()                     # 3.11 新增
        return f"{type(current).__name__}: {current.args[0]}"


# 3.11 起 int <-> str 有位数上限，可用 sys.set_int_max_str_digits 调整
int_digits_limit = sys.get_int_max_str_digits()

# inspect.getmembers 新增 is_class 参数；traceback.TracebackException.from_exception 可直接构造
members = inspect.getmembers(Color, inspect.ismethod)
tbe = traceback.TracebackException.from_exception(ValueError("boom"))
traceback_text = "".join(tbe.format())

# hashlib.file_digest：3.11 起不用再手写 while 循环
file_digest = hashlib.file_digest(io.BytesIO(b"3.11"), "sha256").hexdigest()

# datetime.UTC：datetime.timezone.utc 的新别名
utc_alias = datetime.UTC is datetime.timezone.utc


# =====================================================================
# 10. PEP 594 —— “死电池”被移除
#     cgi / cgitb / crypt / imghdr / mailcap / msilib / nis / nntplib /
#     ossaudiodev / pipes / sndhdr / spwd / sunau / telnetlib / uu / xdrlib
#     以及它们的 cgi.escape / cgi.parse_header / crypt.crypt 等便利函数。
# =====================================================================
def no_dead_batteries() -> str:
    return "telnetlib / cgi / pipes / crypt ... 均已在 3.13 前移除"


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

    # 普通 except 与 3.11 的 except* 并列展示
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

    match literals:                                   # 3.10 引入，3.11 继续支持
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
    async def run_all() -> tuple:
        return await task_group_demo(), await timeout_demo()

    loop = asyncio.new_event_loop()
    try:
        task_bits, timeout_result = loop.run_until_complete(run_all())
    finally:
        loop.close()

    demo = {
        "PEP654 except*": (
            parse_batch({"a": "1", "b": "x", "z": "9", "y": "nope"}),
            parse_batch_ok({"a": "1", "b": "2"}),
        ),
        "ExceptionGroup 拆解": split_group(build_group()),
        "asyncio.TaskGroup": task_bits,
        "PEP678 add_note": noteless_traceback(),
        "PEP646 TypeVarTuple": (
            repr(make_array(2, 3, 4)),
            make_array(2, 3, 4).first(),
            pass_through("a", 1, True),
            apply_all([len, str], [1, 2]),
        ),
        "PEP673 Self": (Shape2D(1, 2).with_size(3, 4).__class__.__name__,
                         Square(2).scaled(3).__class__.__name__,
                         Square(2).clone().__class__.__name__),
        "PEP675 LiteralString": literal_string_demo(),
        "PEP655 dataclass_transform": (PointModel.__annotations__, PointModel.x, PlainModel()),
        "typing Never/assert_type": (describe(1), describe("s")),
        "enum 3.11": (
            Color.RED, f"{Color.RED}", Mode.FAST, repr(Mode.SLOW),
            Level["MID"], Level("mid"), Level("HIGH"), Level(20), Bits.READ | Bits.WRITE, Temperature.WARM.celsius,
        ),
        "asyncio.timeout/Runner": (timeout_result, runner_demo()),
        "contextlib.chdir": chdir_demo(sys.prefix),
        "tomllib": toml_demo(),
        "sys.exception": sys_exception_demo(),
        "int 位数上限 / inspect": (int_digits_limit, len(members), traceback_text),
        "hashlib.file_digest": file_digest[:16],
        "datetime.UTC": utc_alias,
        "PEP594 移除": no_dead_batteries(),
    }
    for key, value in demo.items():
        print(f"{key:<28} -> {value}")
    print("syntax_tour               ->", len(syntax_tour(3, {"a": 1}, [1, 2, 3], "hi")))
    print("Full/Base                 ->", Full.origin(), Full.unit(), Full(2).doubled, Full.tag)


if __name__ == "__main__":
    main()