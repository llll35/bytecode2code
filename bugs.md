# 项目缺陷清单（bugs.md）

> 最后更新：2026-10-22。状态含义：
> **已修复** / **部分修复** / **未修复** / **不适用**。
> 复现与验证命令见文末。

---

## 2026-10-22 修复摘要

本轮继续修 `with` / `try` 交织的结构。核心是 3.11/3.12 的 `with` 退出调用：
`pyvers/decomp311.py` 在合成 3.9 形状的 `POP_BLOCK` 时**替换**掉了退出调用的
第一个操作数，3.9 形状的 `__exit__(None, None, None)` 需要三个操作数，缺一个
就把 reader 的栈模型弄乱了——`with` 后面的 `return` 读不回来。

| # | 缺陷 | 影响版本 | 根因 / 修法 |
|---|------|----------|-------------|
| 9 | `with` 里的 `try` 整块丢失 | 3.9 – 3.12 | `_find_pop_block()` 把外层 `with` 的 `POP_BLOCK` 当成了 `try` 的结束（两者紧挨着）。现在先看候选后面是不是紧跟着另一个 `POP_BLOCK`——是的话前面那个属于内层块 |
| 10 | `with` 后面的 `return` 丢失 | 3.11 / 3.12 | 同上：`with` 的退出调用少一个操作数，栈模型留下残值，`return` 读不回来。退出调用的操作数现在保留 |
| 11 | `with` 吞掉了 `try` 的 `return` | 3.11 / 3.12 | `_with_exit_terminator()` 会跳过外层块的 `POP_BLOCK`，于是落在 `try` 体的返回值上。现在遇到 `POP_BLOCK` 就停——除非 `with` 的体留下了值（那说明 `return` 属于 `with`） |
| 12 | `with` 后面多出一条 `while True:` | 3.12 | 3.12 在 `with` 的体要算返回值时，handler 结尾是一条**回跳**（回到块后面的代码），reader 把它当成了循环的回边。现在整个 handler 被丢掉 |
| 13 | `with` 后面多出一条 `continue` | 3.9 – 3.12 | 退出调用后面跟着的「回环跳」到底是 `continue` 还是循环自己的回边，无法从字节码上区分。现在只有 `with` 的体是空的（`continue` 会立刻离开体）时才当成 `continue` |

### 仍未修复

* **D2**：`try` 块内的 `break` / `continue`（3.11 / 3.12 的 handler 被放到循环
  之外，循环回边与真实 `continue` 同形）。
* **D4**：循环的 `else` 子句。3.9/3.10 把 `else` 放在循环的出口目标上，与
  「循环之后的代码」无法区分；3.11/3.12 同样如此。
* **缺陷 21**：3.12 的 PEP 695 类型参数。
* `with a as x, b as y:` 被拆成两个嵌套的 `with`（语义相同，AST 不同）。
* `try` 里的 `with` 后面跟 `return`（3.11 / 3.12）：`with` 的体在 `try` 里
  结束得太早，`return` 的位置仍然读不准。

---

## 2026-10-21 修复摘要

本轮修了 8 个缺陷，跨 3.9–3.12 四个后端。核心问题有���个：3.11/3.12 的
`finally` handler 被误当成 bare `except`，于是 `try/finally` 整体读错。

| 命令 | 修复前 | 修复后 |
|------|--------|--------|
| `python main.py selftest` | 373 项检查，**13 项失败** | 394 项检查，**0 项失败** |
| `python -m tests.run` | 61/66 | **68/72**（新增 6 项回归语料；剩下的 4 项失败都在 3.12 组） |

逐项修复：

| # | 缺陷 | 影响版本 | 根因 |
|---|------|----------|------|
| 1 | `try/finally` 被读成 `try/except/else` | 3.11 / 3.12 | `pyvers/decomp311.py` 的 `_analyse_handlers()` 把没有 `CHECK_EXC_MATCH` 的 handler 一律改写成 3 个 `POP_TOP`（3.9 的 bare `except` 形状），`finally` handler 因此被读成 `except` 子句，而内联副本被读成 `else` 子句 |
| 2 | 嵌套 `try/finally` 直接崩溃 | 3.11 / 3.12 | 同上：崩溃点正是把 `finally` handler 当成 `except` 链解析 |
| 3 | 实参里嵌套的方法调用丢失 | 3.11 / 3.12 | `analyse()` 用单个 `pending_depth` 跟踪待定的方法 loader，内层 loader 会把它重置，外层 `CALL` 因此认不出自己 |
| 4 | `except ... as e: return X` 丢掉 `return` | 3.11 / 3.12 | `_name_cleanup()` 返回了 `SWAP` 的偏移而不是清理 handler 的偏移；`_name_body_end()` 返回区域末尾而不是最后一条指令的偏移 |
| 5 | `POP_BLOCK` 丢失 | 3.11 / 3.12 | `_translate_step()` 的 `SWAP` / `BINARY_OP` 等分支提前 `return`，跳过了补 `POP_BLOCK` 的那段代码 |
| 6 | 模块级 `<code object ...>` 泄漏、`else` 吞掉后续定义 | 3.12 | `_redirect_handler_exits()` 只在 `target == entry.end` 时搬走 tail，函数级的 tail（handler 回跳到的那段代码）留在原地，被 `else` 子句吞掉 |
| 7 | `try` 体末尾的 `return` 丢失 | 3.9 – 3.12 | 返回值在 `POP_BLOCK` **之后**才加载（常量无需计算），于是它不在 reader 读到的 body 范围里 |
| 8 | `with` 里的 `try` 多出 `return None` | 3.10 | `_find_pop_block()` 把 `with` handler 里的 `POP_BLOCK` 当成了 `try` 的结束 |

另外新增了 `tests/cases.py` 的三个回归语料：`tryreturn`（缺陷 7）、
`nestedcall`（缺陷 3）、`finallyclause`（缺陷 1/2）。

### 仍未修复

* **D2**：`try` 块内的 `break` / `continue`（3.11 / 3.12 的 handler 被放到循环
  之外，循环回边与真实 `continue` 同形）。
* **D4**：循环内的 `else` 子句与带 `break` 的 `else`。
* **缺陷 21**：3.12 的 PEP 695 类型参数。
* `try` 里的 `with` 后面跟 `return`：3.9 正确；3.10 把 `return` 读进了 `with`
  的块体（`with` 的退出调用后紧跟的就是它）；3.11 / 3.12 则相反——`return`
  整个消失（`with` 的退出调用少一个操作数，reader 的栈模型因此留下一个残值，
  `return` 读不回来）。

---

## 2026-10-20 修复摘要

本轮修掉三个 3.11/3.12 的语义级缺陷，并把测试运行器改成按版本分发。

| 命令 | 结果 |
|------|------|
| `python -m tests.run` | **61/66**（3.9 组 34/34 全通过；3.12 组 27/32） |
| `python main.py selftest` | 373 项检查，**3 项失败**（未变） |
| `probe_controlflow.py` | 30 项失败（原 32，`d3_two_levels` 3.11/3.12 已修） |
| `probe_probes_multiver.py` | 3.9 **31/31**、3.10 29/31、3.11 27/31、3.12 27/31 |

`prime.py`（3.12 真实样本）的 AST 差异从 303 行降到 113 行，模块结构
（`try/except`、类、方法）完整保留——此前整个 `ReciprocalAnalyzer` 类都会
塌成 `ReciprocalAnalyzer = 'ReciprocalAnalyzer'`。

---

## 2026-10-18 扫描摘要

实际执行验证命令后的结果：

| 命令 | 结果 |
|------|------|
| `python -m tests.run` | 34/35 round-trip 一致，`probe_retfinally` 字节码差异 |
| `python main.py selftest` | 373 项检查，**3 项失败**（2026-10-18 晚修复 D3 后；扫描时为 15） |
| `probe_controlflow.py` | 32 项失败（D1-D4 跨 3.9-3.12；D3 两例已修后，原为 40） |
| `probe_multiwith.py` | **所有版本均严重错乱**（`return x+y` → `(x+y)(None,None,None)`） |

### 新发现 / 恶化

- **多 with + return 全面崩溃**：此前文档称 P0-1 已修复（3.12），3.11 仍有问题；实测 3.9/3.10/3.11/3.12 全部错误。`with a as x, b as y: return x+y` 反编译为 `(x+y)(None,None,None)`，语义完全错误。
- **match 带 dict/list 模式**：3.11/3.12 输出完全错误语义（`if 1: v=('k',); ('k',); return v`），不是等价转换。
- **3.11/3.12 嵌套 try/finally 崩溃**：`DecompilationError: <module> produced no statements from 6 instructions`。

### 与旧清单的差异

旧清单声称 D1 的 `class`/`import` 已修复、`def` 仍有问题；实测 D1 的 class/import 确实通过，但 D2/D3/D4 状态与旧清单一致（未修复或部分修复）。主要差异是 selftest 实际有 15 项失败，而非 0 项。

---

## 控制流重建缺陷

### 缺陷1：D1 — 模块级 try/except 吞掉后续定义
**严重程度**：高
**问题描述**：模块级 try/except 后跟类、函数、导入定义时，后续定义被吞没或错误输出（`Foo = 'Foo'`、`return None`）。
**影响范围**：Python 3.12 模块级代码
**状态**：**部分修复**（2026-10-21）。3.9 / 3.10 / 3.11 已正确；3.12 的
`class`/`import`/`def` 用例现在都正确了——模块级 tail（handler 回跳到的那段
代码）会被搬到 handler 之后，函数定义不再被读成 `<code object ...>` 赋值。
**剩余**：`tests/samples/prime.py` 里最后一个函数 `main` 仍然缺失——它自身
的 `while True` + `try/except` 结构（见缺陷 2）让 reader 在那里失控。
**根因（已修部分）**：`pyvers/decomp311.py` 的 `_save_tail_for_merge()` 只处理
「handler 回跳到 entry.end」的形态；3.12 对模块级 try/except 会**同时**在
handler 前后各放一份尾部代码，而当前逻辑没有丢弃前一份。2026-10-21 改为按
handler 回跳的**目标**搬走 tail，函数级的 tail 同样被搬走。

### 缺陷2：D2 — try 块内 break/continue 恢复错误
**严重程度**：高
**问题描述**：try 块内包含 break/continue 时控制流恢复错误。
**影响范围**：3.9 / 3.10 / 3.11 / 3.12
**状态**：**未修复**。`try/finally` + `break`/`continue` 仍会产生重复语句与多余的
`break`/`continue`（见 `_scratch/probe_controlflow.py` 的 `d2_*`）。
**根因**：`finally` 的 handler 副本未被跳过，且循环回边被误判为 `continue`。

### 缺陷3：D3 — 深度嵌套 finally 折叠
**严重程度**：高
**问题描述**：3.11/3.12 中深度嵌套 finally 被折叠，丢失嵌套结构。
**影响范围**：3.11 / 3.12（3.9/3.10 亦受影响）
**状态**：**部分修复**（2026-10-20）。3.9 / 3.10 的 `d3_two_levels` 与
`d3_nested_finally` 已通过；3.11 / 3.12 的 `d3_two_levels` 已通过
（`probe_controlflow` 中由 `AST DIFF` 变为 `ok`）。`d3_finally_with_except`
与 3 层以上的 `d3_nested_finally` 仍失败。

**2026-10-20 追加修复**：3.11+ 里「保护区间为空」的 `try/finally` 不产生
body 异常表项，只剩子句的 cleanup 项，于是整个 `try` 消失。两种形态都已恢复：

- **独立形态** `try: return X` / `finally: C`：从 handler 里的子句副本反推
  内联副本位置，在其前合成 `SETUP_FINALLY` 并紧跟 `POP_BLOCK`（空 body）。
  `retfinally.a` 在 3.11/3.12 上现已与原始字节码**完全一致**。
- **嵌套形态**（外层 `try` 内再套一层）：同上，但只在恰好一个表项块时启用。
  3 层以上不启用——Rewriter 会把中间层 handler 的 `PUSH_EXC_INFO` 改写成
  `POP_TOP`，合成两个指向它的 `SETUP_FINALLY` 会**过度嵌套**，比现状更差。
- `finally: pass` 刻意不恢复：空子句不改变语义，把出口留成直线代码更简单也
  更正确（否则锚点会落进出口序列中间，把返回值丢掉）。

**2026-10-21 追加修复**：`finally` handler 之前被 `_analyse_handlers()` 当成
bare `except` 改写（3 个 `POP_TOP`），于是整个 `try/finally` 被读成
`try/except/else`——子句变成 `except` 体，内联副本变成 `else` 子句，嵌套
`try/finally` 还会直接崩溃。新增 `_is_finally_handler()` 区分三种 handler：
`finally`（跑子句再 `RERAISE`）、bare `except`（`PUSH_EXC_INFO` 后紧跟
`POP_TOP`）、`with` handler（紧跟 `WITH_EXCEPT_START`）。`finally` handler
现在保持原样，3.11 / 3.12 的 `try/finally`、嵌套 `try/finally`、
`try` 里的 `finally` 全部恢复正确。

**剩余**：`retfinally.b`（`finally: pass`，语义等价但字节码缺 NOP）、
`retfinally.c`（`return y` 是死代码，编译期已删除，不可恢复）、
3 层嵌套、`d3_finally_with_except`。

**根因（已修部分）**：`bytecode2code/decompiler.py` 的 `SETUP_FINALLY` 分支里，
「try 体只有一个空 body 时把滞后 `return` 收回」的逻辑被错误地缩进到了
`if cont is None:` 的 `else` 分支内，于是 `cont is None and ...` 恒为假，
整段成为死代码——`return` 永远被抬到 `finally` 之外。已把分支改为
`if cont is not None: trailing.append(cont)` / `else: 消耗回边 + 收回 return`，
并新增「嵌套 `try` 的滞后 `return` 下沉到最内层空 body」的分支。
**剩余根因**：3.11 / 3.12 走 `decomp311.Decompiler311` 自己的
`_collect_finally_body()`（override），其 `resume`/body 形状与基类不同，基类
修复未覆盖；`d3_finally_with_except` 另有 `else` 误生成与 `except ... as e`
隐式清理（`e = None; del e`）重复发射的问题。

**2026-10-18 追加修复 — `probe_retfin`/`retfinally` 的 case `c`**：
`def c(n): try: return n+1 finally: y=n*2; return y` 在 3.9 上曾被截断为
`return n`，已通过「re-emit 分支加 `and not try_stack` 条件」修复（3.9 通过）。
注意：**3.10 / 3.11 / 3.12 的 case `c` 无法复原**——`return y` 位于恒返回的 try
体之后，是不可达死代码，3.10+ 在编译期已把它优化删除，字节码里没有
`LOAD y; RETURN`，反编译无从恢复。这是编译期的信息丢失，属**已知限制而非缺陷**。

### 缺陷3b：3.12 两参数切片丢失操作数（已修复 2026-10-20）
**严重程度**：高（语义错误）
**问题描述**：3.12 把 `BUILD_SLICE 2` 与消费它的下标操作折叠成单个
`BINARY_SLICE` / `STORE_SLICE`，而 `decomp311` 两个都没有处理分支。容器和
上下界被直接丢弃，`s[i:j]` 反编译成栈上残留的值（通常是 `None`）：
`return s[-n:] if cond else s` 变成 `if cond: return None`。
**影响范围**：3.12（3.11 仍用 `BUILD_SLICE 2` + `BINARY_SUBSCR`，不受影响）
**修复**：展开回 `BUILD_SLICE 2` + `BINARY_SUBSCR` / `STORE_SUBSCR`。
注意只有两参数形态被折叠，三参数切片仍是 `BUILD_SLICE 3`——这也是
`probe_slices` 一直通过的原因。

### 缺陷3c：3.11/3.12 实参里嵌套调用的方法调用被丢弃（已修复 2026-10-20，2026-10-21 补全）
**严重程度**：高（语义错误）
**问题描述**：`d.append(str(x))` 反编译成 `(str(x))`，接收者和方法名都没了；
在循环里还会多出一条 `x = d`。
**根因**：`Rewriter.analyse()` 用单个 `pending_depth` 跟踪方法 loader 之后的
栈深度，遇到内层 `CALL` 就把 `pending_depth` 置 `None`，于是外层 `CALL`
再也认不出自己是 loader 的调用。另外 3.11 把调用的栈效果拆成
`PRECALL argc`（`-argc`，被当簿记跳过）和 `CALL`（`-1`），只读 `CALL` 的
`stack_effect` 得不到 `-(argc+1)`。
**修复**：非方法调用时继续跟踪深度，并按两者合并后的 `-(argc + 1)` 递减。
**2026-10-21 补全**：上面只修好了「实参里是普通调用」的情形；实参里**又是一个
方法调用**时（`f.write('\n'.join(results))`），内层的 loader 会把唯一的
`pending_depth` 重置，外层的 `CALL` 仍然认不出自己。改为用一个深度**栈**跟踪
每个待定 loader：每个 loader 各记一个「上方还有几个栈槽」，任何入栈的指令
都会让所有待定 loader 的计数加一，loader 被自己的调用消费时弹出，并把父
loader 的计数按 `-(argc + 1)` 递减。

### 缺陷4：D4 — try/except/else 子句边界
**严重程度**：中
**问题描述**：try/except/else 之后的代码边界处理错误。
**影响范围**：3.9 起（文档写的「Python 3.1」为笔误）
**状态**：**部分修复**。`else` 子句本身与 `else` 后紧跟语句的常见形态已正确；
循环内的 `else` 与带 `break` 的 `else` 仍不完整（见 `d4_else_in_loop`、
`d4_else_with_break`）。其中 `d4_else_in_loop` / `d4_else_with_break` 的剩余差异
部分源于字节码不可区分（见下节）。
**2026-10-21 修复（3.12）**：3.12 把 `else` 子句内联在 try 体之后，而 handler
回跳到的是整个 `try` 之后的那段代码——两者之间没有别的标记，reader 于是把
`try` 之后的代码也读成了 `else` 子句（`clause(x)` 的 `b = a + 1` 被吞进
`else`）。修复在 `pyvers/decomp311.py`：`_redirect_handler_exits()` 现在按
handler 回跳的**目标**搬走 tail（原来只在 `target == entry.end` 时搬），tail
因此落到 handler 之后，`else` 子句的边界恢复正确。

### 缺陷22：`try` 体末尾的 `return` 丢失（已修复 2026-10-21）
**严重程度**：高（语义错误，语句整条消失）
**问题描述**：`try: g(p); return 1` 反编译后只剩 `try: g(p)`，`return 1`
整条消失。`try: g(p); return p + 1` 则正常——两者的差别只在返回值是不是常量。
**影响范围**：3.9 / 3.10 / 3.11 / 3.12（基类 reader 的问题，三个新版本都继承）
**根因**：编译器把 `POP_BLOCK` 放在返回值的**前面**——常量不需要计算，等
`POP_BLOCK` 弹掉块之后再 `LOAD_CONST` 也一样。于是返回值不在 reader 读到的
body 范围里，reader 以为这个 `try` 没有返回值。
**修复**：`bytecode2code/decompiler.py` 新增 `_return_value_after_pop_block()`，
认出「`POP_BLOCK` 之后紧跟一个 `LOAD_*` 和一个 `RETURN_VALUE`」的形态，把
那段读成 body 的最后一条语句。`finally` 块与值为 `None` 的 `return` 不走这条
路：前者后面的代码属于整个 `try` 之后，后者与隐式 `return None` 不可区分。

### 缺陷23：3.11/3.12 的 `POP_BLOCK` 丢失（已修复 2026-10-21）
**严重程度**：高（块结构错乱）
**问题描述**：`try` / `with` 的块在某些指令结尾处没有 `POP_BLOCK`，块的范围
因此算错，`except ... as e` 的隐式清理块尤其明显：`return len(e) * 2` 的
`e = None; del e` 跑进了子句体。
**影响范围**：3.11 / 3.12
**根因**：`pyvers/decomp311.py` 的 `_translate_step()` 里，`SWAP`、`BINARY_OP`、
`BINARY_SLICE` 等操作码各自走一条提前 `return` 的分支，跳过了函数末尾统一
补 `POP_BLOCK` 的那段代码。
**修复**：把 `_translate_step()` 拆成外层（负责补 `POP_BLOCK`）与内层
（`_translate_instruction()`，只翻译一条指令），任何提前返回的分支都会经过
外层的补齐。

### 缺陷4b：`longchain` — 链式比较后多出死 `return`（已修复 2026-10-19）
**严重程度**：低
**状态**：**已修复**。`return a < b < c < d < e < g` 反编译后多一条不可达裸
`return`（链式比较末跳落到函数隐式 `return None` 尾声）。修复：
`_drop_dead_tail` 丢弃「前一条是 Return/Raise/Break/Continue 的裸 `return`」。
3.9 / 3.10 / 3.12 通过（3.11 原已通过）。

## 字节码不可区分（已知限制，非缺陷）

以下失败是**编译期信息丢失 / 两种源码编译成同一字节码**，反编译无从区分，
强行「修复」会破坏其它用例，故保留为已知限制：

- **`except_as` / `exceptions`**：函数末尾显式 `return None` 与隐式尾声字节码相同。
  反编译选择省略（发射会污染所有无显式 return 的函数）。
- **`whileelse`**：`while ... else` 无 `break` 时，`else` 体与循环后代码字节码相同。
- **`retfinally` 的 `c`（3.10/3.11/3.12）**：`return y` 位于恒返回的 try 体之后，
  是死代码，3.10+ 编译期已优化删除。
- **`d4_else_in_loop` / `d4_else_with_break`**：`except E: pass` 与
  `except E: continue` 字节码相同（空体 + 跳回循环头）；且 handler 回边与 else
  都指向循环头，`else` 边界不可判定。
- **D2 若干 break/continue 形态**：循环回边与真实 `continue` 同形。

## 未实现的语法特性

### 缺陷21：3.12 PEP 695 类型参数未支持（未修复）
**严重程度**：高（输出不是合法 Python）
**问题描述**：`def f[T](x: list[T]) -> T:`、`class C[T]:`、`type Alias = int`
反编译后完全错误且无法解析。最小复现：

```python
def first[T](xs: list[T]) -> T:
    return xs[0]
```

得到

```python
def first():
    """T"""
    return ((T := 'T'),)
```

**影响范围**：3.12（PEP 695 专属语法）
**根因**：3.12 把类型参数放进 `MAKE_FUNCTION` 的 type-params 元组，再经
`SET_FUNCTION_ATTRIBUTE` / `CALL_INTRINSIC_1` 设到 `__type_params__`；
`decomp311` 没有对应分支，把元组构建误读成函数体，`T := 'T'` 的 walrus
形状因此泄漏到输出里。
**现状**：`tests/samples/py312_syntax_demo.py` 在 3.12 上的输出无法 parse
（`invalid syntax`，第 42 行 `return ((T := ),)`），但 `tests/run.py` 与
`selftest` 都没有覆盖这个样本的解析性，所以一直没暴露。

## 工程与文档缺陷

### 缺陷5：架构分离不清晰
**严重程度**：中
**状态**：**已改善**。`pyvers` 现在是可导入的包（相对导入、统一模块身份），
版本差异集中在 `decomp_compat.py`（3.10）与 `decomp311.py`（3.11/3.12），
错误类型统一到 `bytecode2code/errors.py`。

### 缺陷6：测试覆盖不足
**严重程度**：中
**状态**：**已改善**。新增针对 `del`/`assert`/类关键字/链式赋值/`UNPACK_EX`/
相对导入/长链式比较/嵌套作用域/异常处理/`try`+`finally` 中 `return` 的回归用例，
以及跨版本控制流探针 `_scratch/probe_controlflow.py`。

### 缺陷7：缺少项目文档
**严重程度**：中
**状态**：**已修复**。新增 `README.md`（用途、架构、命令、运行测试、已知限制）。

### 缺陷8：调试代码未清理
**严重程度**：低
**状态**：**已修复**。根目录 35 个一次性脚本已移入 `debug/archive/`，
并新增 `.gitignore`。

### 缺陷9：魔法数字和硬编码引用
**严重程度**：低
**状态**：**未修复**。`.kiro/specs/` 中仍有硬编码行号引用（如 tasks.md 的
"line 186"）。

### 缺陷10：类型提示不完整
**严重程度**：低
**状态**：**未修复**。

### 缺陷11：缺少依赖管理文件
**严重程度**：中
**状态**：**已修复**。新增 `pyproject.toml`（无第三方依赖；`bytecode2code`
可安装，`pyvers` 依赖仓库布局故不打包）。

### 缺陷12：缺少 CI/CD 配置
**严重程度**：中
**状态**：**已修复**。新增 `.github/workflows/ci.yml`（round-trip + 跨版本自检）。

### 缺陷13：测试运行不统一
**严重程度**：低
**状态**：**已修复**。`python -m tests.run` 与 `python main.py selftest`
两条命令；`python -m bytecode2code` 亦可用。
**2026-10-20 补修**：`tests.run` 原先假设语料只有一个版本，混入 3.12 的
`prime.pyc` 后必然在另一版本的样本上抛 `bad marshal data`（两条命令实际上都
跑不起来）。现改为按版本分组、每组用匹配的解释器执行，并用版本感知的反编译器
（`pyvers.decomp_compat.make_decompiler`）而非固定的 3.9 reader 处理样本。

### 缺陷14：缺少 CHANGELOG
**严重程度**：低
**状态**：**已修复**。新增 `CHANGELOG.md`。

### 缺陷15：异常处理不一致
**严重程度**：中
**状态**：**已修复**。新增 `bytecode2code/errors.py` 异常层级；CLI 把包内错误
转成一行消息 + 非零退出码，traceback 只留给真正的 bug。

### 缺陷16：缺少性能基准测试
**严重程度**：低
**状态**：**未修复**。

### 缺陷17：缺少发布流程
**严重程度**：中
**状态**：**已改善**。`pyproject.toml` 提供打包元数据与 console script。

### 缺陷18：嵌入 Python 版本增加复杂性
**严重程度**：低
**状态**：**已修复**。`README.md` 说明了 `embed_python/` 的用途与版本覆盖。

### 缺陷19：缺少错误码和错误处理类
**严重程度**：低
**状态**：**已修复**。见缺陷15。

### 缺陷20：硬编码的版本检查
**严重程度**：低
**状态**：**已改善**。magic 表集中在 `bytecode2code/pyc_parser.py` 与
`pyvers/versions.py`，并有 `get_python_version()` 单一入口。

## 验证命令

```
python -m tests.run                 # 68/72 round-trip 一致（按版本分组，见下）
python main.py selftest             # 394 项检查，0 失败
python -B _scratch/probe_controlflow.py 3.9 3.10 3.11 3.12
python -B _scratch/probe_probes_multiver.py 3.12   # 探针语料单版本往返（换 3.9/3.10/3.11）
python -B _scratch/probe_retfin.py          # try/finally 中 return 的形态（host 3.13，全失败）
python -B _scratch/probe_multiwith.py       # 多上下文管理器 with（全版本失败）
python -B _scratch/probe_star_match.py      # except* 与 match
```

`tests/run.py` 的语料并非单一版本（`checkerboard`、`py39_syntax_demo`、
`feature_matrix` 是 3.9，`prime` 是 3.12），而 `marshal` 不跨版本，所以运行器
按头部版本把样本分组，每组交给匹配的 `embed_python/` 解释器执行，并用同一
解释器重新编译结果。源码形态的探针在**每个**版本都跑一遍——它们是唯一能分别
压到 3.9/3.10/3.11/3.12 四条后端路径的语料。

`_scratch/` 下的脚本是临时探针（`.gitignore` 只排除 `_scratch/pyc/`），
`probe_probes_multiver.py` 直接对 `tests/cases.py` 的 `PROBES` 做单版本往返。
