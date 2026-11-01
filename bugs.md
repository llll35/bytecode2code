# 项目缺陷清单（bugs.md）

> 最后更新：2026-11-01。状态含义：
> **已修复** / **部分修复** / **未修复** / **不适用**。
> 复现与验证命令见文末。

---

## 2026-11-01 门禁状态快照

| 命令 | 结果 |
|------|------|
| `embed_python/python-3.12/python.exe tests/run.py` 的 ROUND-TRIP | **263/263** |
| `tests/run.py` 的 CONTROL FLOW | **77/77**（七版本各 11/11） |
| `python main.py selftest` | **2/2** 通过 |
| `embed_python/python-3.12/python.exe tests/test_cfg.py` | 8 项失败，与 HEAD 逐字一致（既有，非本轮回退） |

ROUND-TRIP 全部逐字节一致。自 2026-10-30 的 234/263 起，本轮修复见下节 H/I/J。

---

## 2026-11-01 修复摘要

| 命令 | 修复前 | 修复后 |
|------|--------|--------|
| ROUND-TRIP | 262/263 | **263/263** |
| 3.11 组 | 48/48 | 48/48（H/I 移植后曾回退到 46/48，J 项的 reader 侧改法把它取回来） |
| 3.12 组 | 48/49 | **49/49** |

| # | 缺陷 | 影响版本 | 根因 / 修法 |
|---|------|----------|-------------|
| H | 跳转按偏移解析时命中「后面重排的那段尾巴」，`main` 截断 | 七版本 | `_find_target_idx` 原先取第一条 `offset >= target` 的指令。尾巴（`_save_tail_for_merge`）在合并点重排到 out-of-line handler **之后**，于是仅仅「排在这个地址后面」的指令会排在携带这个地址的指令前面。现在先找**精确**等于该地址的一条，找不到才退回到第一条更大的；七份 `decompiler.py` 同一条锚点移植 |
| I | handler 尾部被复制的隐式 `return None` 删掉后，跳向它的分支落空 | 3.11–3.15 | `_redirect_handler_epilogues` 只删副本、不动指向它的跳转。现在 `_drop_return_none` 记下「删掉的地址 → 留下的那份地址」（`_kept_copy_before` 往前找最近一条整份存活、且自己后面仍跟着 `RETURN` 的 `return None`），`_retarget_dropped_epilogues` 再把瞄准被删地址的分支改瞄到留下的那份上 |
| J | 内联推导式让外层方法调用退化成 `([c for c in x])` | 3.12–3.15 | 3.12 把列表推导就地展开成 `LOAD_FAST_AND_CLEAR`/`BUILD_LIST`/`FOR_ITER`/`END_FOR`，`_lift_comprehension` 之后把整段换成一次调用；但 `analyse()` 的 `pending_depths` 是按**原始**那段流水算的，容器入栈、借用的局部出栈全都算进待定 loader 的深度，于是 `"".join(...)` 的 `LOAD_METHOD` 对不上自己的 `CALL`，被发成 `CALL_FUNCTION`，reader 把接收者丢掉。现在 `analyse()` 用 `_comprehension_run_end` 整段跳过推导式及其收尾，只统计它前面那个可迭代对象 |

### 关于「函数末尾显式 `return None`」的读法（J 的副产品）

I 落地后，`_validate_input`（3.12）多出一条凭空 `return None`：删掉副本、把
分支改瞄到**留在原地**的那份之后，这份尾巴排在 `try` 的 `POP_BLOCK` 与其
out-of-line handler 之间，于是整条流水的末尾不再是它。原先按 AST 放宽
`_drop_dead_tail` 可以压掉，但同一条规则会连 3.11 `probe_except_as` 里源码
**真写了** `return None` 的四个函数一起压掉（往返 48/48 → 46/48）。

现在的判据回到指令流：`_is_epilogue_pair` 除「这对 `LOAD_CONST None` /
`RETURN_VALUE` 是流水最后两条」之外，还认「其后每一条指令都落在已被
`_handled_ranges` 消费掉的 out-of-line 区间里」——3.9 只有一份尾声、谁都跳进
它，3.11+ 复制的那份停在 handler 前面，尾巴后面只剩 reader 早已读完的 handler。
`_tail_is_jump_reached` 仍在原地：一条 `JUMP_FORWARD`/`JUMP_ABSOLUTE` 瞄准它是
源码级 `return` 留下的唯一痕迹，此时不能丢。

### 仍未修复：`try` 体内的条件 `break` + `except` + `finally`

门禁语料没有这一形状，七组全绿不等于它已修好。下面的片段在 3.11–3.15 仍然读错
（3.14/3.15 造出 `except ValueError: break` 与假的 `else:`，3.12 把整个循环读成
`try/except/else/finally`，3.11 输出重复的 `while True`）：

```python
def f(x):
    while True:
        try:
            if x:
                break
        except ValueError:
            pass
        finally:
            print(1)
```

`break` 在 `try` 体末尾被跳转线程成 NOP，`except` 链与 `finally` 又要 handler 排在
循环出口之后——同族的无条件 `break`（`flow_break_in_try`）已由 G 项在七组跑通，条件
`break` 走的是 `_analyse_exception_loop_exits` 的另一条分支。另外 3.11/3.12 与
3.14/3.15 的 `_analyse_exception_loop_exits` 是**两套不同的算法**（2609 vs 2827
字符，3.14/3.15 那套还带着 `has_normal_back_edge` 与 `getattr(self, '_loop_breaks',
{})` 的旧写法），修之前得先把两边对齐，否则一条分支上的修法在另一边不生效。

---

## 2026-10-30 修复摘要

| 命令 | 修复前 | 修复后 |
|------|--------|--------|
| CONTROL FLOW | 72/77 | **77/77** |
| ROUND-TRIP | 232/263 | **234/263**（无回退） |
| `main.py decompile boom.pyc`（3.9） | 只剩循环体前两句 | ROUND-TRIP **identical**、AST 与源码 **identical** |

| # | 缺陷 | 影响版本 | 根因 / 修法 |
|---|------|----------|-------------|
| E | `try/finally` 的子句被读成 `pass`，`try` 之后的语句一起丢失 | 3.10 | `flow_finally_return`：`except` 子句用 `return` 离开时，外层 `finally` 的内联副本落在**整条 except 链的已消费区间** `(17, 32)` 里，`_parse_except_handlers` 把这段标进了 `_handled_ranges`；随后外层 `_collect_finally_body` 去读内联副本（25..28），`_emit_statements` 返回空，子句就成了 `pass`。现在在「量出了子句长度却一句没读出来」时改读 handler 里的那份逐字副本，并从 handler 之后续读——与 handler 无正常路径时（B 项）的读法一致。`py310Decompiler/decompiler.py:1504`。+1 |

改动只在 `py310Decompiler/decompiler.py`。3.11–3.15 的 `flow_finally_return` 走的是
`decomp311` 的异常表通道，本次未触碰，也未验证移植（移植前需单独跑四版本门禁）。

| F | `boom.pyc`（3.9）六处控制流全塌：`continue`/`break` 退化成 `while True`，内层 `try/except as/finally` 与三层嵌套 `finally` 整段丢失 | 3.9 | 见下节，5 处独立根因，现已 ROUND-TRIP **逐字节一致**、AST 与源码**逐字一致** |

| G | `flow_nested_finally_reraise` 塌成 `for …: pass` + 假 `else: while True: pass`；`flow_try_except_else_finally`、`flow_finally_return` 的 `finally` 子句读成 `pass` | 3.12–3.15 | 见「`flow_nested_finally_reraise`（3.12–3.15）」一节，10 处改动，CONTROL FLOW 现 **77/77** |

### `boom.pyc`（3.9）五处根因

`main.py decompile boom.pyc` 原先只吐出循环体的前两句。逐个定位：

1. **跳转瞄准了被合并掉的 `EXTENDED_ARG`。** `disassembler._merge_extended_args`
   把前缀折进后一条指令、后一条保留自己的地址，而 `dis` 解出来的 `argval` 仍指前缀
   那条被删掉的地址：循环头记成 14，回边却是 `JUMP_ABSOLUTE 12`，`continue` 对不上
   任何头，被读成新的 `while True`。现在 `_resolve_extended_targets`
   （`py39Decompiler/disassembler.py:148`）在合并之后把这类目标向后取整到下一条存活
   指令，一次性喂给所有按偏移比较的读者（`_match_loop_jump`、`_inline_copy_back_edge`、
   `_emit_for_else`、`_emit_conditional`、`SETUP_FINALLY` 的 handler 头都受益）。
2. **出口前的 `finally` 副本没被藏住。** `_hide_escape_copies` 认定「副本之后就是出口」，
   但 `with`/内层 `try` 的卸载排在副本与真正的 `break`/`continue` 之间。新增
   `_past_teardown`（`decompiler.py:1666`）跨过这段卸载（遇分支标签即停），并把紧跟
   `RERAISE` 的副本也判为展开路径——子句跑完就往上抛，绝不是源码写法。
3. **副本只藏了模式窗口那么长。** 子句里含 `try` 时，3.9 把这条 `try` 的 handler 也
   一起贴在每个出口上；`_copy_matches` 只按子句长度截窗，窗口之外的嵌套 handler 就
   被读成第二份同样的子句（`deep`/`deepest` 重复三次即此）。`_copy_handler_end`
   （`decompiler.py:1691`）沿副本内的 `SETUP_*` 推到其 handler 的最后一个 `RERAISE`，
   整个尾巴一起标掉。同一规则补进了 `_handler_end`：handler **第一条**就是
   `SETUP_FINALLY` 时原先直接 `return j`（空区间），子句因此在源码之后重演一遍。
4. **循环体被两条回边切成两句。** `with` 收尾会闭合循环两次——正常路径一次、异常
   路径经 handler 再一次，编译器把正常那次写在前面，中间只剩卸载。原先只认最右一条，
   左边那条就成了没人写的 `continue`。`_first_loop_close`（`decompiler.py:5759`）在
   回边之前全是卸载类指令时改用最左一条定界。
5. **`if trigger: pass` 被整个丢掉。** `_emit_conditional` 见到「then/else 都空」就
   直接跳过；而这种分支落在紧跟其后的那条指令上，正是 3.9 编译空体 `if` 的唯一形态，
   测试表达式仍然进字节码。`decompiler.py:5613` 起补出 `if cond: pass`。

第 1 项对七个后端的 `disassembler.py` 是同构的（都跑 `_merge_extended_args`），本轮只改了
3.9 那份并单独复验；其余四项在 3.10+ 的 `decompiler.py` 副本里同样存在，但 3.10/3.11/3.14
对 `boom.py` 还有各自的其它缺陷（`None(None, None, None)` 一类的 `__exit__` 误读），
未一并移植。

### `flow_nested_finally_reraise`（3.12–3.15）根因定位

3.11 已通过，3.12 起失败，差异在**布局**而不是规则：

* 3.11 把 `for` 循环内层 `try` 的 handler 放在循环体内，循环出口是一条
  `JUMP_FORWARD`（`FOR_ITER` 精确指向它），`try` 语句之后的代码排在所有 handler 之后。
* 3.12 的 `FOR_ITER` 指向 `END_FOR`（被 `DROPPED` 删掉，reader 向后取整，CFG 要求精确），
  而内层 `try` 的两个 handler（`-> 164`、`-> 222`）被整体外提到循环出口**之后**、
  `try` 语句之后那段代码（128..162，外层 `finally` 的内联副本 + `return 0`）的**后面**。

于是合成流里 `SETUP_FINALLY`（off 66 → 222）的 handler 落在循环区间之外，reader 认不出
这个块，循环体塌成 `for i in range(x): pass`，内层子句被当成循环之后的顺序代码重读，
并多出一个假的 `else: while True: pass`。

**落地的修法**（3.12/3.13 一套，3.14/3.15 再加一条 reader 规则；四份
`decomp311.py` + `decompiler.py` 逐锚点移植，未整文件覆盖）：

1. **`Rewriter._live_offset`**：区域名下的 handler 头可能正是被本 pass 删掉的
   `PUSH_EXC_INFO`（`finally` 清理段的第一条）。把 `SETUP_FINALLY` 的目标改成它
   存活成的那条指令，否则 reader 与 CFG 拿到一个不属于任何指令的地址，块匹配不上，
   `POP_BLOCK` 被算到更内层的块上，整个 `try` 少读一层。
2. **`Rewriter._share_body_close` + `close_extras` / `_fresh_offset`**：一条语句把
   几个块压在同一条指令上，3.9 在体末逐个 `POP_BLOCK` 连着弹；异常表只在最内层
   handler 上点名一次体的末尾，外层块的弹法被送到自己 handler 之前——那位置在循环
   **之外**，reader 于是把循环体算到那条 `POP_BLOCK` 就结束，整条 `try` 消失。现在
   把这些弹法重新锚到共享的体末，并按压栈顺序补发额外的 `POP_BLOCK`，每条分配一个
   不与真实指令重合的地址（分支只能瞄准第一条）。
3. **`Rewriter._place_one_close`**：`nested` 只看 `with` 之外的嵌套 handler 目标；
   起始落在展开桩（`COPY`/`POP_EXCEPT`/`RERAISE`）里的 span 不计入体末；回退找锚点
   时跳过 `DROPPED` 与 `NOP`；同一锚点被两个块共用时走 `close_extras` 而不是抢占地址。
4. **reader 的副本匹配带上参数**（`_ANY_ARG` / `_pattern_item` / `_ADDRESS_OPS`）：
   子句副本是逐字的，常量名与变量名也要比；只有跳转豁免——每份副本重定位自己的目标。
   外层 `finally` 的子句恰好与内层子句同头（都是 `print('…')`）时，光比 opname 会把
   两份不同文本认成同一子句。
5. **`_inline_clause_end` 的排空守卫**：内联段也写出来的那份排空（`POP_TOP` /
   `POP_EXCEPT`）是两侧共同的子句正文，要参与比较，不能被当展开标记跨过去。
6. **`_is_exc_drain`**：3.11 之后排空只剩一条 `POP_TOP`，紧跟 `POP_EXCEPT`。
7. **`_recover_else_clause`**：两条 `POP_BLOCK` 背靠背时（`except` 块先弹、外层
   `finally` 块后弹），中间没有 `else` 可写。
8. **`Decompiler311._collect_finally_body`**：块弹法落在 `else` 体末时，紧跟其后的
   是 `except` 链而不是子句，两侧一步就分道；此时改从 `SETUP_FINALLY` 指向的那份副本
   读子句并从其后续读。
9. **`Decompiler311._handler_end`** 交回共享走法：handler 到传播异常的 `RERAISE`
   结束，而不是第一个 `RETURN_VALUE`——会 return 的子句在不 return 的那条路上仍要重抛。
10. **3.14/3.15 独有**：`_parse_handler_body` 里，子句以「向后跳」离开时（3.11+ 把外层
    `finally` 的内联副本停在 handler **前面**，跳的是那份副本），只要目标小于
    `POP_EXCEPT` 的偏移且对不上任何循环回边，子句就止于 `POP_EXCEPT`、这条跳转不输出。
    两条改动没有动 `_analyse_handlers` 里的 `loop_cleanup` 启发式——它在本案仍会误触
    （把名字清理当成循环收尾丢掉），但读者现在能把丢掉的结构读回来。

结果：CONTROL FLOW **77/77**（3.12/3.13/3.14/3.15 各 11/11），ROUND-TRIP
232/263 → **234/263**（新增 `probe_retfinally` 在 3.14、3.15 两例），其余失败与
本轮无关（`probe_exceptions`、`probe_cls`、`probe_classkw` 等既有缺陷）。
3.14 组 40/48、3.15 组 38/48；3.15 的 `probe_yield`/`probe_yieldexpr` 仍是 3.15
自身的旧缺陷，未在本次范围内。

---

起点是上一轮留下的 41/77（HEAD 的重写器 + 当前工作树），本轮验证节点：
41 → **49** → **55** → **56**。全部改动仍未提交，也未推送。

| 命令 | 修复前 | 修复后 |
|------|--------|--------|
| `python -m tests.run` 的 CONTROL FLOW | 41/77 | **56/77**（最近一次 3.11 组 10/11 → **11/11**） |
| `python -m tests.run` 的 ROUND-TRIP | 232/263 | 232/263（最近两次完整输出逐字一致） |
| `python -m tests.test_cfg`（3.9） | 9/9 | 15/15（含 6 项输出回归），3 项 3.11 专项跳过 |
| `python tests/test_cfg.py Rewriter311Tests`（3.11） | 未添加 | 3/3 |
| `python tests/test_cfg.py OutputNormalizationTests`（七版本分别运行） | 未添加 | 各 6/6，共 42 项通过 |
| 3.9 / 3.10 控制流组 | 11/11、11/11 | 11/11、11/11 |

| # | 缺陷 | 影响版本 | 根因 / 修法 |
|---|------|----------|-------------|
| A | 嵌套 `try` 被摊平成一个 `try` 的子句列表 | 3.11–3.15 | 3.11 的嵌套关系写在表的**退链**里：一条区域的 `end` 正好是下一条的 `start`。`Rewriter` 只做单步回溯，于是内层的 `SETUP_FINALLY` 落在外层区域内，reader 把整棵树读平。现在 `_region_start` 沿退链传递回溯，并且会越过「嵌套子句的 handler 头」（`_table_heads`）；`try_replace` 分支（handler 头被改写成 `DUP_TOP`）也要发 `SETUP_FINALLY`（`_emit_block_setups`）；整个区域就是嵌套语句的块，其 `POP_BLOCK` 补在 handler 头之前（`_close_before_head`）。+8 |
| B | `finally` 只在 handler 里留了一份文本 | 3.11–3.15 | `flow_finally_return`：`try` 的每条出口都跑完子句后离开，**没有正常路径**，因此表里根本没有内联副本区。reader 侧 `_collect_finally_body` 增加「块弹到 handler 头之间什么都没有」的分支——就在 handler 处读子句、从 handler 之后续读；`Decompiler311._collect_finally_body` 原本整个遮蔽了这段逻辑，现在把该情形交回 `super()`。同时 `_hide_escape_copies` 不再要求出口副本前面必须有 `POP_BLOCK`（3.11 没有块栈），但**裸副本**必须紧跟出口（`limit=2`）：`try: g() finally: h()` 的两种读法指令序列相同，放宽一步就会把 `g()` 当成副本吃掉（曾在 3.15 上把 ROUND-TRIP 拖到 231/263，已复验回到 232）。+5 |
| C | `try/except/else/finally` 的外层块关得太早 | 3.11 | `else` 段的 `end` 恰好是 `except` 链的 handler 头，`_place_one_close` 的 `limit = min(nested)` 把外层弹块钉在了那里，内联 `finally` 副本泄漏成顺序代码。`nested` 现在只认真正的嵌套块——`with` 的 handler（`self.with_targets`）；同一语句的 `except` 链不构成边界。并补上「区域一路顶到 handler」的兜底与退避桩（`COPY`/`POP_EXCEPT`/`RERAISE`，`_unwind_stubs`）跳过。+1 |

**注意**：C 的完整形态（连 `limit` 一起去掉）在 3.11 上是对的，在 3.12/3.13/3.15
上会把 `flow_with_in_try_return` 打回去（实测 6→5、6→5、5→5、5→4）。逐版本试过，
只有「`nested` 限定为 `with` 处理器 + 兜底 + 桩跳过」这一组合在七个后端上都不回退。
另外 `decomp311.py` 的五份副本**并非逐字节相同**（3.11 是 CRLF，3.12–3.15 是 LF，
且各自有版本特有方法），移植要按锚点逐份核对，不能直接 cp。

### 3.11 嵌套 finally 补修

`PUSH_EXC_INFO` 被删除后，合成的 `SETUP_FINALLY` 仍指向已消失的 handler 头。
reader 会把缺失地址向后取整，CFG 却要求目标地址精确存在，因此漏掉了两层
`finally` 区域，内层子句被错误读成 `else`。`Rewriter._resolve_handler_targets`
现在把 setup 的目标解析到 handler 第一条存活指令，**不移动原指令地址**。
另外 `_handler_end` 复用基类的分支感知扫描，避免在条件 `return` 处提前结束，
把 handler 余下的副本重复输出到整个 `try` 之后。

本次只改 `py311Decompiler/decomp311.py`。3.12/3.13 的内存实验使
`with_in_try_return` 从通过变为失败，未移植；较新版本仍需独立修复。
新增 3 项专项测试检查 handler 精确目标与区域保留、条件返回后的 handler 边界、
往返一致且 AST 中没有重复子句。原 3.9 手工边界断言未变，七份 reader 哈希一致。
完整门禁仍因已有失败返回 1；此次只新增一个通过项，无通过项回退。

### 合并 try 外壳与模块隐式返回

用户命令 `embed_python/python-3.10/python.exe main.py decompile test_sc.pyc`
中的两层 `try` 来自编译器把 `except` 链与 `finally` 保护区分开编码。
现在仅在输出 AST 时合并：外层只有 `finally`、没有 handler/else、body 只有
一个带 handler 且没有自身 `finally` 的 `try`。真实嵌套异常链、双层 finally、
带前后语句或自身 handler 的外壳均保留；重建期间不改变区域结构。

模块的递归分支仍使用同一个 `<module>` code object，不能仅靠递归参数
`is_module` 判断返回是否合法。`RETURN_VALUE`、`RETURN_CONST` 与 `with`
退出路径现在区分模块作用域，模块禁用 return 型条件表达式折叠，函数返回保留。
模块分支中复制的隐式返回仍用于识别 `else` 边界，空分支保留 `pass`，
避免去掉返回后把 `else` 变成无条件语句或丢失条件求值。

验证：原始 CLI 输出可编译，与 `test_sc.py` 的 AST 完全一致，与原 `.pyc`
往返等价；`nested_try_chain()` 的真实嵌套保留。新增 6 项输出回归在七个
解释器均通过，覆盖合并/不合并边界、递归作用域、模块空分支、if/else/elif、
with、三元赋值及函数返回。最终完整门禁输出与修复前逐字节一致：
ROUND-TRIP 232/263、CONTROL FLOW 56/77，仍因已有失败退出 1。
七份 `decompiler.py` 一致，七份 `cfg_flow.py` 一致且本次未改动。

### 仍未修复

* `flow_nested_finally_reraise`：3.12–3.15 仍失败，3.11 已修复。
* `flow_try_except_else_finally`：3.12–3.15（3.11 已修）。同一条源码头在 3.12 上
  需要另一处修正，`limit` 相关的两种改法都不动它。
* `flow_for_else_nested` / `flow_try_in_loop_with`（3.12–3.15）、
  `flow_break_in_try`（3.12/3.13）、`flow_continue_in_finally`（3.14/3.15）、
  `flow_with_in_try_return`（3.15）。
* 本文档里 **「2026-10-27 修复摘要」出现了两次且内容重复**（本轮未合并，
  避免把上一轮的记录一起改错）。
* CFG 手工边界仍只适用于 3.9，另有 3.11 重写器专项；输出规范化测试已覆盖七版本。
  `independent_control_flow/` 目录本轮未改动。
* 额外模块探针仍暴露独立问题，未扩大到本次修复：模块 `except E as e` 的恢复、
  3.9 双层 if/else 的内层 else 丢失、3.11+ 空 try 的嵌套 finally 恢复、
  3.15 模块 if/with/else 把 else 语句重复读入 with。这些不代表全部模块形状已通过。

**2026-11-01 复核**：上面前五条里的 `flow_*` 全部已过——G 项（10 处改动）加本轮 H/I/J
之后 CONTROL FLOW **77/77**、ROUND-TRIP **263/263**。`independent_control_flow/` 已删除
（见缺陷21）。重复的「2026-10-27 修复摘要」两节仍未合并。

---

## 2026-10-27 修复摘要

本轮把 `except` 子句的边界交给控制流图（`cfg_flow.py`）：子句用 `return` 离开
`try` 时，它弹出的那个 `POP_BLOCK` 属于**外层** `finally` 区域，贴在后面的那份
`finally` 内联副本就不再算进子句体。

| 命令 | 修复前 | 修复后 |
|------|--------|--------|
| `python -m tests.run` 的 CONTROL FLOW | 45/77 | **46/77**（3.10 组 10/11 → **11/11**） |
| `python -m tests.run` 的 ROUND-TRIP | 232/263 | 232/263（未回归） |
| `python -m tests.test_cfg` | 9/9 | 9/9 |

| # | 缺陷 | 影响版本 | 根因 / 修法 |
|---|------|----------|-------------|
| 14 | `except` 子句里多出一次 `finally` | 3.10 | `_parse_handler_body` 从前向扫描一路读到 `RETURN_VALUE`，把外层 `finally` 的内联副本读进了子句体——`except ValueError: g(3); return 2`。3.9 同一形状是对的，靠的是 `_hide_escape_copies` 把那段标成 handled range；这条规则在 3.10 上恰好失效：出口上的 `POP_BLOCK` 正是图给出的区域终点（`try_end_idx`），被「终点后面那份副本是子句本身」排除掉。现在改为直接问图：这个 `POP_BLOCK` 关的是哪个 `finally` 区域（`_enclosing_finally_copy`），副本与区域的 handler 逐步对齐（`_inline_clause_end`），对齐的段落从子句区间里挖走，子句自己的出口留在后面（`_emit_except_clause`） |

### 仍未修复

* **3.11+ 的同一族缺陷换了成因**：`flow_finally_return` / `flow_reraise_chain` /
  `flow_try_except_else_finally` / `flow_nested_finally_reraise` 在 3.11–3.15 仍
  失败。原因是 `decomp311.Rewriter` 在进入 reader 之前就把 3.11+ 的
  `try/finally` 整个内联掉了——实测该后端看到的指令流里**根本没有 `finally`
  区域**（`_exception_regions` 只剩一个 `except`），引擎自然无从判断副本归属于谁。
  要修这一族，必须让引擎直接读 `co_exceptiontable`，而不是在合成流上补规则；
  `cfg_flow.py` 的模块 docstring 声称已经这么做，实际代码里一次都没有读过。
* **D2**：`try` 块内的 `break` / `continue`（3.11 / 3.12 的 handler 被放到循环
  之外，循环回边与真实 `continue` 同形）。
* **D4**：循环的 `else` 子句。3.9/3.10 把 `else` 放在循环的出口目标上，与
  「循环之后的代码」无法区分；3.11/3.12 同样如此。
* **缺陷 21**：3.12 的 PEP 695 类型参数。
* `with a as x, b as y:` 被拆成两个嵌套的 `with`（语义相同，AST 不同）。
* `try` 里的 `with` 后面跟 `return`（3.11 / 3.12）：`with` 的体在 `try` 里
  结束得太早，`return` 的位置仍然读不准。

---

## 2026-10-27 修复摘要

本轮把 `except` 子句的边界交给控制流图（`cfg_flow.py`）：子句用 `return` 离开
`try` 时，它弹出的那个 `POP_BLOCK` 属于**外层** `finally` 区域，贴在后面的那份
`finally` 内联副本就不再算进子句体。

| 命令 | 修复前 | 修复后 |
|------|--------|--------|
| `python -m tests.run` 的 CONTROL FLOW | 45/77 | **46/77**（3.10 组 10/11 → **11/11**） |
| `python -m tests.run` 的 ROUND-TRIP | 232/263 | 232/263（未回归） |
| `python -m tests.test_cfg` | 9/9 | 9/9 |

| # | 缺陷 | 影响版本 | 根因 / 修法 |
|---|------|----------|-------------|
| 14 | `except` 子句里多出一次 `finally` | 3.10 | `_parse_handler_body` 从前向扫描一路读到 `RETURN_VALUE`，把外层 `finally` 的内联副本读进了子句体——`except ValueError: g(3); return 2`。3.9 同一形状是对的，靠的是 `_hide_escape_copies` 把那段标成 handled range；这条规则在 3.10 上恰好失效：出口上的 `POP_BLOCK` 正是图给出的区域终点（`try_end_idx`），被「终点后面那份副本是子句本身」排除掉。现在改为直接问图：这个 `POP_BLOCK` 关的是哪个 `finally` 区域（`_enclosing_finally_copy`），副本与该区域的 handler 逐步对齐（`_inline_clause_end`），对齐的段落从子句区间里挖走，子句自己的出口留在后面（`_emit_except_clause`） |

### 仍未修复

* **3.11+ 的同一族缺陷换了成因**：`flow_finally_return` / `flow_reraise_chain` /
  `flow_try_except_else_finally` / `flow_nested_finally_reraise` 在 3.11–3.15 仍
  失败。原因是 `pyNNDecompiler/decomp311.py` 的 `Rewriter` 在进入 reader 之前就把
  3.11+ 的 `try/finally` 整个内联掉了——实测该后端看到的指令流里**根本没有
  `finally` 区域**（`_exception_regions` 只剩一个 `except`），引擎自然无从判断
  副本归属于谁。要修这一族，必须让引擎直接读 `co_exceptiontable`，而不是在合成流
  上补规则。`cfg_flow.py` 的模块 docstring 原先声称已经这么做，本轮已改成实际状态。
* **D2**：`try` 块内的 `break` / `continue`（3.11 / 3.12 的 handler 被放到循环
  之外，循环回边与真实 `continue` 同形）。
* **D4**：循环的 `else` 子句。3.9/3.10 把 `else` 放在循环的出口目标上，与
  「循环之后的代码」无法区分；3.11/3.12 同样如此。
* **缺陷 21**：3.12 的 PEP 695 类型参数。
* `with a as x, b as y:` 被拆成两个嵌套的 `with`（语义相同，AST 不同）。
* `try` 里的 `with` 后面跟 `return`（3.11 / 3.12）：`with` 的体在 `try` 里
  结束得太早，`return` 的位置仍然读不准。

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
**状态**：**已改善**。原条目说的 `pyvers` / `bytecode2code` 包已在重构中移入
`old/`；现在是七个自包含的 `pyNNDecompiler/` 目录，互不 import，版本差异集中在
各自的 `decomp_compat.py`（3.10）与 `decomp311.py`（3.11+），异常表回到 3.9 形状
后才进 reader。代价是 `decompiler.py` 有七份副本，改动必须**按锚点**移植。
错误类型每份后端各有 `errors.py`。

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
**2026-10-30 补修**：`.gitignore` 声明忽略的 `embed_python/`、`debug/`、
`_scratch/`、`__pycache__/`、`.workbuddy-ai/` 仍有 **9815** 个文件被 git 跟踪，
门禁声明的「按需下载」与实际布局相反。现全部移出索引（磁盘文件未删），
跟踪文件从 9961 降到 112；`_scratch/` 改为整目录忽略。根目录另存的一次性脚本
（`apply_fix3.py`、`apply_fixed39.py`、`fix2.py`、`fix_fixed.py`、
`propagate_*.py`，都是「拿一份文件覆盖七个后端」的工具，与按锚点移植的规则冲突）
和 `tmp.txt`、`awkprof.out` 已删除；`1.py`、`crash_test.py`、
`decompile_test_sc.py`、`recursion_bomb_gen.py` 移入 `tests/repro/`；
`FixedDecompiler39/`、`py311_x` 移入 `old/`。`boom.py`、`test_sc.py` 留在根目录
（本文件按路径引用）。

### 缺陷9：魔法数字和硬编码引用
**严重程度**：低
**状态**：**未修复**。`.kiro/specs/` 中仍有硬编码行号引用（如 tasks.md 的
"line 186"）。

### 缺陷10：类型提示不完整
**严重程度**：低
**状态**：**未修复**。

### 缺陷11：缺少依赖管理文件
**严重程度**：中
**状态**：**未修复**。曾记为「已修复（新增 `pyproject.toml`）」，但仓库里没有
这个文件——见缺陷22。项目本身无第三方依赖，缺的是打包元数据与 console script。

### 缺陷12：缺少 CI/CD 配置
**严重程度**：中
**状态**：**未修复**。曾记为「已修复（新增 `.github/workflows/ci.yml`）」，
仓库里没有该目录——见缺陷22。门禁目前只能手动跑 `tests/run.py`。

### 缺陷13：测试运行不统一
**严重程度**：低
**状态**：**已修复**。`python main.py selftest` 与 `embed_python/python-X.Y/python.exe
tests/run.py` 两条命令。`python -m tests.run` 只在宿主 `python` 能读该 payload 时可用，
嵌入式发行版不把工作目录放进 `sys.path`，在它们里面会抛
`ModuleNotFoundError: No module named 'tests'`；`python -m bytecode2code` 随包一起没了。
**2026-10-20 补修**：`tests.run` 原先假设语料只有一个版本，混入 3.12 的
`prime.pyc` 后必然在另一版本的样本上抛 `bad marshal data`（两条命令实际上都
跑不起来）。现改为按版本分组、每组用匹配的解释器执行，并用版本感知的反编译器
（各后端的 `make_decompiler`）而非固定的 3.9 reader 处理样本。

### 缺陷14：缺少 CHANGELOG
**严重程度**：低
**状态**：**已修复**。新增 `CHANGELOG.md`。

### 缺陷15：异常处理不一致
**严重程度**：中
**状态**：**已修复**。每份 `pyNNDecompiler/errors.py` 提供同一套异常层级
（`Bytecode2CodeError` → `PYCError` / `UnsupportedBytecodeError` /
`DecompilationError`）；CLI 把包内错误转成一行消息 + 非零退出码，
traceback 只留给真正的 bug。

### 缺陷16：缺少性能基准测试
**严重程度**：低
**状态**：**未修复**。

### 缺陷17：缺少发布流程
**严重程度**：中
**状态**：**未修复**。曾记为「已改善（`pyproject.toml` 提供打包元数据与
console script）」，仓库里没有这个文件——见缺陷22。

### 缺陷18：嵌入 Python 版本增加复杂性
**严重程度**：低
**状态**：**已修复**。`README.md` 说明了 `embed_python/` 的用途与版本覆盖。

### 缺陷19：缺少错误码和错误处理类
**严重程度**：低
**状态**：**已修复**。见缺陷15。

### 缺陷20：硬编码的版本检查
**严重程度**：低
**状态**：**已改善**。magic 表原以为集中在 `bytecode2code/pyc_parser.py` 与
`pyvers/versions.py`；`py39Decompiler` … `py315Decompiler` 的
`independent_control_flow/` 是同一批占位工具，2026-10-30 全部删除（见缺陷21）。
现每份 `pyNNDecompiler/pyc_parser.py` 各自持表，`main.py` 按 header 选后端。

### 缺陷21：3.9 的后处理用硬编码源码字符串去重
**严重程度**：中
**状态**：**已修复（删除）**。`py39Decompiler/decompiler.py` 原先在
`_emit_statements` 之后调用
`independent_control_flow/full_engine.ControlFlowEngine.rebuild_try_finally_raise()`，
该函数把相邻重复、且**字面量等于** `"raise"`、
`"raise RuntimeError('hit 3')"`、`"print('inner finally always run')"`
的语句删掉——这三条文本抄自 `tests/cases.py:495` 的那条探针，不是控制流规则。
同一个类的 `reconstruct_exception_table()` 直接返回三个空列表，
`apply_none_filter()` / `clean_unbound_del_e()` 是对输出字符串做 `replace`。

实际它是**恒等函数**：`_emit_statements` 返回 `List[ast.stmt]`，
`isinstance(s, str)` 对每个元素都是 `False`，`line` 恒为 `""`，
而 `""` 不在那三条字面量里，所以一句都删不掉。已连同调用、import 和整个
`py39Decompiler/independent_control_flow/`（3.10+ 的六份副本本轮早先已删）
一起移除，`_emit_statements` 之后直接进 `_drop_dead_tail`。
删除后七组门禁逐项复核，与删除前一致（ROUND-TRIP 234/263、CONTROL FLOW 77/77，
`test_sc.pyc` 在 3.9/3.10 的 AST 仍与原源码一致）。

真正需要的那条规则早就在 reader 里：出口内联副本 + 再抛由
`_collect_finally_body` / `_hide_escape_copies` 按形状识别，见 B、G 两项。

### 缺陷22：文档描述不存在的产物
**严重程度**：中
**状态**：**部分修复**。仓库里从来没有 `pyproject.toml`、`.github/workflows/ci.yml`
或 `.kiro/specs/`（`git log` 无记录），本文件缺陷11/12/17 的「已修复」与
`CHANGELOG.md` 的 `### Added` 段都把它们算成了交付物；缺陷5/6/7/11/13/15/18/20
引用的 `pyvers/`、`bytecode2code/` 包也已在重构中移入 `old/`。
2026-10-30 重写 `README.md`：按七份 `pyNNDecompiler/` 后端描述布局，
删除双前端（`bytecode2code` + `pyvers`）与「3.13/3.14 只出规格化反汇编」的
过期结论，说明 `skeleton`/`ir`/`code-info` 现在只是 `decompile` 的别名，
并补上嵌入式解释器跑门禁的方式。历史条目保留原文，本项负责记下差异。

### 缺陷23：引导脚本硬编码绝对路径且一直跑不起来
**严重程度**：低
**状态**：**已修复**。`tests/selftest_310plus.py` 原先写死
`os.chdir(r"D:\py\bytecode2code")`，换成别的目录就找不到 `embed_python/`；
更要命的是它在嵌入式解释器里跑 `-m tests.selftest`，而嵌入式发行版不把
工作目录放进 `sys.path`，必然 `ModuleNotFoundError: No module named 'tests'`，
偏偏 `capture_output` 之后只打印 stdout，stderr 被丢掉，于是每个版本都显示
`FAILED (exit 1)` 而看不出原因（`python -m tests.selftest --all` 一直是 15/15 绿的）。
现在根目录由 `__file__` 推出，子进程按**脚本路径**调用 `tests/selftest.py`
（它自己会把仓库根放进 `sys.path`），失败时打印 stderr，版本号可以作参数传。
2026-10-30 复验：3.10–3.14 各 2/2、3.15 3/3 通过。

## 验证命令

```
embed_python/python-3.12/python.exe tests/run.py   # ROUND-TRIP 263/263、CONTROL FLOW 77/77
embed_python/python-3.14/python.exe tests/run.py   # 同一命令，任一版本作宿主都会扇出全部七组
# 单版本组（换掉三处版本号即可）：
BYTECODE2CODE_TESTS_GROUP=3.14 BYTECODE2CODE_TESTS_OUT=_scratch/g314.json \
  embed_python/python-3.14/python.exe tests/run.py
python -m tests.test_cfg            # 3.9：15 项通过，3 项 3.11 专项跳过
embed_python/python-3.11/python.exe tests/test_cfg.py Rewriter311Tests  # 3 项通过
# 七版本分别执行下面的输出回归（将 3.10 替换为对应版本）：
embed_python/python-3.10/python.exe tests/test_cfg.py OutputNormalizationTests  # 各 6 项通过
embed_python/python-3.10/python.exe main.py decompile test_sc.pyc  # AST 与原源码一致，往返等价
                                    # 前提是 test_sc.pyc 由 3.10 编译：`python main.py compile test_sc.py --version 3.10`
embed_python/python-3.9/python.exe tests/selftest_310plus.py       # 逐版本 selftest（缺陷23 修好后，3.10–3.14 各 2/2、3.15 3/3）
python main.py selftest             # 本次 host 3.9：2/2 通过
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

`_scratch/` 下的脚本是临时探针（`.gitignore` 现已整目录忽略，2026-10-30 前只排除
`pyc/` 和文本输出，另有 65 份被跟踪，已移出索引），
`probe_probes_multiver.py` 直接对 `tests/cases.py` 的 `PROBES` 做单版本往返。
