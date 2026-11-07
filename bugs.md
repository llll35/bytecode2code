# 项目缺陷清单（bugs.md）

> 最后更新：2026-11-06。状态含义：
> **已修复** / **部分修复** / **未修复** / **不适用**。
> 复现与验证命令见文末。

---

## 2026-11-06 boom.py 3.12/3.13 with 收尾被误判 break（AD）

3.12/3.13 的 `with` 体塌成 `continue`、try 跑到循环外，根因在
`Rewriter._analyse_exception_loop_exits`：凡异常表 `entry.end` 落在 NOP 上就注册
`_loop_breaks[NOP]=下一指令`。内层 `with` 的正常路径收尾锚点（3.12 offset 422、
3.13 offset 436）正是这样一个 NOP，被当成循环 break。`_translate_instruction`
的 `loop_exit` 分支先于 `with_closes` 的 POP_BLOCK 发射并提前返回，发出合成
`JUMP_ABSOLUTE` 而非 POP_BLOCK；缺了收尾，`ExceptionAnalyzer` 把外层 with 的
pop（读端 index 87）记成 index 21 处 try/finally 的 body pop，try 体结束点与
with 体结束点重合，try 遂被组装到循环外。3.14 的同位 NOP 发的是 POP_BLOCK
（其 `_loop_breaks` 对 boom 为空），故 3.14 正常。

修正：注册前加守卫 `raw_list[end].offset not in self.with_closes`——with 收尾
锚点是块自身的正常路径结束，不是 break。`with_closes` 在该方法之前已算好。

3.12/3.13：boom 65→53 行，门禁 49/49、48/48。剩余 53 行是内层
try/except/finally（攻击点 3–5）：`except … continue` 读成 break、嵌套 finally
读成 pass、handler 副本泄漏到循环外。源于 try 区域收尾 NOP 上其余的合成
`_loop_breaks`（如 3.12 306→310）发出 3.14 没有的冗余 fall-through 跳转，
`_collect_finally_body` 见 POP_BLOCK 后紧跟跳转即返回空子句。试过更广守卫
（清空全部 loop_breaks→58；正常回边守卫→55 且回退 no_multi_with/
with_plus_nested_finally；跟随跳转→58）均非门禁安全收益，故只保留已验证的
with_closes 守卫。彻底解决需把 `_analyse_exception_loop_exits` 重构到 3.14
的成熟逻辑（含 has_normal_back_edge 守卫），风险较高，留待后续。

脚本：子任务诊断脚本在 `_scratch/`；本轮验证 `_scratch/port_back_edge_guard.py`
（试后回滚）、`_scratch/follow_jump.py`（试后无效）。

---

## 2026-11-06 boom.py 3.11 多 with 出栈点（AC）

3.11 的 `with open("x") as f1, open("y") as f2:` 之前塌成单个 `with`：外层
`with` 的 `POP_BLOCK` 被 `_analyse_with` 锚到 1642（handler 尾部的展开副本），
而非体自身的 294。`_analyse_with` 取「最后一个可达、且落在 `__exit__` 调用前的
区域」作体收尾；嵌套 `with` 的 handler 在展开时也跑外层管理器的 `__exit__`，
异常表把那段也记到外层 handler 名下。原有过滤只排除「覆盖另一 handler 目标」的
区域，但这段展开区域**起点在嵌套 handler 之后**却仍可达（嵌套 handler 的正常
出口跳到它），于是 `max` 选中了它。

修正：再加一条排除——起点 ≥ 另一 `with` handler 头部的区域是展开尾部，不是体。
外层候选遂回到 {192, 294}，取 294；内层不变（272）。多 with 结构恢复。

3.11：boom 36→33 行，门禁 48/48；`no_deep_finally` 31→17、`no_continue`
35→31、`no_except_as` 35→32。剩余差异是 with 体内 try/except/finally 的体边界
被 `_exception_regions` 过度记账（把 with 的 POP_BLOCK 记成 try 的 body_pop），
与 3.12/3.13 同族，属读端图 walk 的核心难题，本轮未动。

仅改 py311（3.14/3.15 已 IDENTICAL，不冒险；3.12/3.13 由并行任务处理）。
脚本：`_scratch/port_with_unwind_range_311.py`。

---

## 2026-11-06 boom.py 收尾 3.14/3.15（AA/AB）

血缘修正之后，3.14/3.15 剩 15 行，是两个独立缺陷，本轮各修一个，现已**逐字一致**。

**AA — `with` 重复尾隐藏吞掉循环 else/结尾代码**（`decomp_compat.Decompiler310._process_with`）：
3.10 布局会把「块之后的直线代码」复制一份放在嵌套退出调用之后，读端用
`_handled_ranges.append((tail_end, handler_start))` 把这份副本标成已消费。但当
`with` 是循环体最后一条语句时根本没有这份副本——正常路径经循环回边离开，
`tail_end` 到 handler 之间是循环的 `else` 子句和循环之后的语句，全是真实源码，
被一并隐藏后整段丢失（`FOR_ITER` 退出目标在改写流里无对应指令，读端从
139..227 恢复后跳过 else）。修正：新增 `_with_tail_is_back_edge`，当
`instructions[tail_end]` 是指向 `with` setup 之前的无条件跳转（外层循环回边）
时跳过这次隐藏。3.14/3.15：15→7 行。

**AB — `except … as e` 体内的 `continue` 读成 `break`**（`decompiler._classify_jump`）：
3.11+ 把带 `finally`/`except as` 的 `continue` 编译成先跳到该退出路径上的子句副本
（如 762→934 的 `result.append('mid')`），副本末尾再跳回循环头（1002→28）。
`_match_loop_jump` 只看第一跳，934≥循环退出点就判 `break`。修正：新增
`_continue_through_unwind`，当直接匹配为 break 且是无条件跳转时，沿落点直线 run
走到它自己的无条件跳转——若指回最内层循环头则为 `continue`；真正的 break 落在
循环之后的代码，其下一个跳转不会回到本循环头，re-raise/return 则视为逃逸。
3.14/3.15：7→**0（IDENTICAL）**。

两项都按锚点移植到 3.11–3.15 五个后端，逐组门禁全绿（3.11 48/48、3.12 49/49、
3.13 48/48、3.14 48/48、3.15 48/48），ROUND-TRIP 263/263、CONTROL FLOW 77/77、
selftest 2/2。3.11/3.12/3.13 的 boom 差异属另一族（`with` 体截断 / finally 子句
配对），这两项对它们无副作用但也未消除其主缺陷。

| 版本 | 本轮前 | 本轮后 |
|------|--------|--------|
| 3.11 | 36 | 36 |
| 3.12 | 65 | 65 |
| 3.13 | 65 | 65 |
| 3.14 | 15 | **IDENTICAL** |
| 3.15 | 15 | **IDENTICAL** |

脚本：`_scratch/port_with_guard.py`、`_scratch/port_chain_continue.py`、
诊断 `_scratch/who_marks.py`（定位超大 handled range 的来源）。

---

## 2026-11-06 boom.py 血缘修正（Y/Z）

**根因**：`Rewriter._region_start` 把 `finally` 块的 SETUP 起点向前提升时，只要求
两段区域的 `depth` 相等、且候选 handler 地址落在 `[begins, target)` 区间内。
这两条都不是嵌套关系：同一条语句里前后相继的两个块深度相同，两个互不相干的
`try` 语句的 handler 也会偶然满足地址顺序。于是外层 `finally` 的块被开到了
上一个 `try` 的体内，读端把 `except` 的 `continue` 读成 `break`，并把
`for/else` 与结尾的 `try/finally` 整段吞掉。

**修正**：提升前再用异常表本身验证一次血缘——从候选 handler 出发，沿着
"保护该 handler 的那些区域"的 cleanup target 走，走到待提升的目标才算数。
带 `seen` 集合防环。相邻拼接（`entry.end == begins`）那条规则不变。

| 版本 | 修正前 | 修正后 |
|------|--------|--------|
| 3.11 | 36 | 36（本样本无提升，行为不变；与 3.12–3.15 对齐） |
| 3.12 | 80 | **65** |
| 3.13 | 80 | **65** |
| 3.14 | 42 | **15** |
| 3.15 | 42 | **15** |

门禁七组全绿：**340/340**（`embed_python/python-X.Y/python.exe tests/run.py`
逐组跑，ROUND-TRIP 与 CONTROL FLOW 合并计数），3.9/3.10 的 `boom.py` 仍逐字一致。

**试过但回退的方向（3.11）**：把 `finally` 块的 `POP_BLOCK` 挪到内联子句头部
那个填充槽位（3.9 正是写在那里）。子样本上收益很大——`only_with_try`
16→5、`no_multi_with` 45→31、`only_nested_finally` 28→ok——但在 `boom.py`
整体上不能与 `flow_nested_finally_reraise` 同时成立：

- 只在头部补一次出栈：`boom.py` 23 行，`flow_nested_finally_reraise` 门禁回退
  （FOR_ITER 目标 62 vs 51，外层 `finally` 常量丢失）。
- 头部出栈 + 同时删除该区域原有的锚点出栈：门禁 48/48，`boom.py` 反升到 37 行。
- 再放宽 `_close_offset`（分支指向的下一个地址也算出栈地址）：仍 47/48。

结论：3.9 的 `finally` 出栈点数是"每块一次"，而 3.11+ 的正常路径**根本不弹出**
该块——把出栈补回头部会连带改变 `_exc_stack` 的配对，读端在
`nested_finally_reraise` 那种"handler 里还有嵌套 try"的形状上失去正确配对。
这一族需要的是读端按块归属重新配对，而不是在 Rewriter 里补 POP_BLOCK。
相关脚本：`_scratch/port_clause_head_pop2.py`、`_scratch/close_combos.py`、
`_scratch/revert_clause_head.py`（3.12–3.15 未采纳该实验，残差为 0）。

**3.14/3.15 剩下的 15 行**是两个独立缺陷：`except … as e` 体内的 `continue`
被读成 `break`；`for … else` 与结尾 `try/finally` 整段丢失（`FOR_ITER`
的退出目标 512 在改写流里没有对应指令，读端从 139..227 恢复后就跳过了 else
子句）。3.12/3.13 的 65 行以同一族 `with` 体截断为主。

---

## 2026-11-01 门禁状态快照

| 命令 | 结果 |
|------|------|
| `embed_python/python-3.12/python.exe tests/run.py` 的 ROUND-TRIP | **263/263** |
| `tests/run.py` 的 CONTROL FLOW | **77/77**（七版本各 11/11） |
| `python main.py selftest` | **2/2** 通过 |
| `embed_python/python-3.12/python.exe tests/test_cfg.py` | 8 项失败，与 HEAD 逐字一致（既有，非本轮回退） |
| `boom.py` 按 AST 复测 | 3.9、3.10 逐字一致；3.11–3.15 仍 DIFF，剩余形状见「2026-11-04 boom.py 复测（Q/R/S/T）」与「2026-11-04 boom.py 修复 3.10（U/V/W/X）」 |

ROUND-TRIP 全部逐字节一致。自 2026-10-30 的 234/263 起，本轮修复见下节 H/I/J，
其后再补 K/L/M（boom.py 复测一节）。

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

## 2026-11-01 boom.py 复测

压力样本 `boom.py` 只按 AST 与源码逐字一致判定——门禁比的是字节码，覆盖不到它。
本轮先复测，再把它拆成 8 个最小形状逐版本定位（`_scratch/boom_bisect.py`）。

| 版本 | 复测结果 |
|------|----------|
| 3.9 | 上一轮的尾巴重排把它读成 73 行爆炸输出；K 项之后 **AST 与源码逐字一致** |
| 3.10–3.15 | 仍 DIFF；L/M 取回可取的形状，剩余 4 类见下表 |

剩余失败只有 4 类：`for_else`（源码里的 `for … else` 没有 `break`，与「循环之后的
语句」在字节码上同形，信息不在流水里）、`break_in_try`（就是上一节的条件 `break`）、
`deep_finally`（`finally` 里再套 `finally`，3.12 把内层链铺开成 4 份副本）、
`except_as_nested_finally`（3.11–3.15 塌陷成 `pass` 与重复子句）。

| # | 缺陷 | 影响版本 | 根因 / 修法 |
|---|------|----------|-------------|
| K | G 项的尾巴重排在**真** 3.9/3.10 流水上误触发，把 `with` 之后的一段搬进 handler | 3.9 | `_find_stray_block_tail` 把 `SETUP_FINALLY -> 191` 的 target 当成 out-of-line handler，而 3.9 的 target 是**内联**的 `finally` 子句；搬走 `[173,191)` 等于把 `try` 拦腰切断。新增类开关 `HOIST_STRAY_BLOCK_TAILS`：基类 `False`，只有 `Decompiler311` 置 `True`——重排本就是给 `Rewriter` 铺的流水用的 |
| L | 每个函数顶上凭空多一条 docstring（`"""stop"""`、`"""x"""`） | 3.14、3.15 | 3.14 起 CPython 不再把 `co_consts[0]` 预留成 docstring 槽（旧版本无 docstring 时该槽是 `None`），第一个**被使用**的常量就落在 0；`_prepend_function_docstring` 只看「0 是 str」，于是把正文用到的字面量当 docstring 贴回去。docstring 是正文唯一**不会 LOAD** 的常量，判据改为「正文里有 `LOAD_CONST` 取到它就不贴」。同版本 `ast_sweep` 从 2/9 → 3/9（`feature_matrix.py` 取回） |
| M | 以 `if` 收尾的函数把隐式返回读成语句（`if` 体里多一条 `return None`） | 3.10 | `_is_epilogue_pair` 原先只认「这对排在流水最末」或「其后已被 `_handled_ranges` 消费」。3.10 给每条分支各写一份尾声，两份连着排在结尾时前一份也是尾声（`if x: return` 与 `if x: pass` 编出同样的字节），新增这条判据后 3.10 的 `if` 形状 AST 一致 |

**M 的 `with` 分支仍未修**：3.9/3.10 里 `with` 的尾声副本后面还跟着
`WITH_EXCEPT_START` 卸载链，轮到那个 `LOAD_CONST None` 时区间尚未登记，判据拿不到
「后面全是已消费的 handler」，于是 3.9 在函数层、3.10 在 `with` 体层各多出一条
`return None`（字节码仍逐字节一致，只有 AST 差）。`def f(): with a: print(1)` 与
`def f(): with a: print(1); return` 在 3.9/3.10 只差一条 `NOP`，语句级丢弃会打到
真写了 `return` 的样本，故未动。

K/L/M 之后 ROUND-TRIP **263/263**、CONTROL FLOW **77/77** 不变；`ast_sweep` 在
3.9/3.10/3.12 与 HEAD 逐项相同（无回退），3.14/3.15 各 +1。

---

## 2026-11-03 boom.py 深挖（N/O/P）

按 AST 复测 `boom.py`，3.11–3.15 输出里到处是 `None(None, None, None)`，3.14/3.15
更整个函数塌成 `with … : pass` 四行。逐个定位到三处独立缺陷：

| # | 缺陷 | 影响版本 | 根因 / 修法 |
|---|------|----------|-------------|
| N | `with` 体内 `break`/`continue` 退出时，管理器的 `__exit__(None, None, None)` 收尾被当成语句读出（满屏 `None(None, None, None)`） | 3.11–3.15 | 3.11+ 编译器把每次异常退出的 `__exit__` 调用**逐份内联**到 break/continue/return 各路径上；`_analyse_with` 只折叠正文末尾自然落出那一份，循环退出的副本漏网。新增 `Rewriter._drop_with_unwind_teardowns`：以异常表为准（该 run 的起点是某个 `with` handler 保护区的起点、且 CALL 不在 `with_exits` 里即非自然收尾），配合「三个 `None` 之前是语句完成量（POP_TOP/NOP/SWAP/COPY/ROT）而非取可调用对象的 LOAD」这条判据，把 `LOAD_CONST None ×3; CALL; POP_TOP` 整段丢进 `_drops`。真写 `foo(None, None, None)` 的调用总在首个实参前压 `foo`，两条判据同时成立才丢，误伤面为零 |
| O | 嵌套 `with` 的 `SETUP_WITH` 收尾被 CFG 图记到内联 `finally` 的 `POP_BLOCK` 上，`_find_pop_block` 无条件下信它，`with` 体被读短 | 3.14、3.15 | 3.14 的 `with_anchors`/`prefix` 折叠把两个 `SETUP_WITH` 收成**一个** `POP_BLOCK`，共享块栈模拟把嵌套 `finally` 的 pop 记给了外层 `with`（`last_body_pop=88` 早于真实收尾）。在 `_find_pop_block` 的图短路前加判据：`is_with` 时，只有该 pop 之后确实跟着 `__exit__` 收尾（`_with_exit_terminator != -1`）才信它，否则退回向后扫描重取 |
| P | `if 条件: continue` 嵌在 `for → with → try` 里时，reader 读完 `continue` 就终止整个 `with` 体，3.14/3.15 塌成四行 | 3.14、3.15 | 与 O 同源：3.14 折叠后 `try`（内层 `SETUP_FINALLY`）从图拿到 `last_body_pop=94`，但它被读在 `with` 体 `[20,80)` 内，94 越过了这个 body 的右界，reader 把整段吞掉只剩 `continue`。给 `_find_pop_block` 增 `limit` 形参（`_process_instruction` 里的 body 右界），当 `last_body_pop >= limit` 视为「记到外层块的 pop」、退回把扫描也夹到 `min(try_end_idx, limit)`；扫描的候选循环与两处空返回一并改用 `scan_end` |

三处改完：3.14/3.15 不再塌陷，`with` 体的 `if:continue / if:break / finally` 逐条读回；3.12/3.13 顶部结构（`for → with → try/finally`）也不再是 `None(…)`。**ROUND-TRIP 263/263、CONTROL FLOW 77/77 全绿不变**。

`boom.py` 剩余错处集中在 D3 一族（`except … as e` 清理守卫 + 3 层嵌套 `finally` +
except 里 `continue`）：`_find_pop_block` 之后仍把 `for … else` 与收尾 `try/finally`
错并进内层 `else`，且深层还有第二处 `None(…)` 泄漏——这是 reader 异常子句归属的
老问题，独立于 N/O/P，后续单独处理。3.9/3.10 无 `Rewriter`，N 的修法不适用。

---

## 2026-11-04 boom.py 复测（Q/R/S/T）

先把复测口径校正过来：之前的临时脚本用**宿主**解释器编译样例、再交给别的后端
读，3.9/3.10 拿到的是 3.13 的字节码，结论自然是假的。现在每个版本都用自己的
`embed_python/python-<ver>/python.exe` 编译并反编译（`_scratch/bisect_ver.py`、
`_scratch/boom_status.py`），八个子形状与整份 `boom.py` 都按 AST 逐字比对。

在此基础上定位到四处独立缺陷：

| # | 缺陷 | 影响版本 | 根因 / 修法 |
|---|------|----------|-------------|
| Q | 循环体里的内联 `finally` 副本被当成「跑向循环头的尾段」搬出循环 | 3.11–3.15 | `_find_stray_block_tail` 判「这段尾段是不是循环体的一部分」时只看**段内**有没有跳回循环头的指令；可内联 `finally` 的副本是先跳到下一份子句副本、再由那份跳回循环头的，段内看不到那一跳，于是整段被搬走，`try/except/finally` 套在 `for` 里就被读成两份。`_runs_back_to_head` 改为沿控制流往外跟（新增 `_flows_to_head`），段内的跳转落到别处时继续跟下去，直到撞上循环头或落进一条不再回头的路径 |
| R | 合并点重发的尾巴把「为别的理由删掉的指令」复活 | 3.11–3.15 | `_save_tail_for_merge` 把尾段整段记进 `_drops`，重发时靠 `_tail_offsets` 取消这些删除；但 3.13 在 `END_FOR` 后面写的那个 `POP_TOP` 早就因为别的理由被删过，重发时却被一起取消删除，凭空多出一条 `POP_TOP`。现在只把**本次真的删掉**的偏移记进 `_tail_offsets`，别的理由删的照旧不复活 |
| S | 跳回 `for` 循环头的指令被当成 `while True` 的回边，循环体在自己内部被重读 | 七版本 | `_handle_plain_jump` 认不出 `continue` 时（循环栈当时是空的）就退化成 `_emit_while_true`，而它不检查回边目标是不是 `FOR_ITER`——于是 `for` 的循环头被当成 `while True` 的头，整个循环体在自身内部又读了一遍，3.12/3.13 上直接 `RecursionError` 崩掉。`_emit_while_true` 的目标若是 `FOR_ITER`/`GET_ITER`，那只能是跳回某个 `for` 循环头（`continue`），不再开第二个循环 |
| T | `try` 套在 `with` 里时，`continue`/`break` 退出路径上的 `finally` 副本被读成语句 | 3.10–3.15 | 编译器在退出路径上写的是「子句副本 → `with` 的收尾 → 跳回循环头」。`_hide_escape_copies` 认得出副本，但只在副本**紧跟其后**找那条跳转；`with` 的收尾插在中间时就找不到，副本被当成正文语句读出。现在先把收尾这段卸栈跳过，再找跳转 |

Q/R/S/T 落地后：

| 版本 | `boom.py` 按 AST 复测 |
|------|----------------------|
| 3.9 | **逐字一致** |
| 3.10 | **逐字一致**（U/V/W/X 四项修完，见下节） |
| 3.11 | 38 行差异 |
| 3.12 | 80 行差异（**不再崩**） |
| 3.13 | 80 行差异（**不再崩**） |
| 3.14 | 42 行差异 |
| 3.15 | 42 行差异 |

子形状复测（`_scratch/bisect_ver.py`）：3.11 的 `except_as_nested_finally` 与
`for_else_break` 由 Q 取回；3.12–3.15 仍在 `except_as_nested_finally`、
`break_in_try`、`for_else_break` 上失败。

**ROUND-TRIP 263/263、CONTROL FLOW 77/77 全绿不变。**

仍未解决的三类（独立于 Q/R/S/T）：

* `except_as_nested_finally`（3.12–3.15）：3.13 把 `finally` 子句**内联**在正路
  上、handler 里另存一份；`_save_tail_for_merge` 认 handler 里那份与正路上那份
  形状相同，就把正路那份丢了，于是外层 `try` 找不到自己的 `POP_BLOCK`
  （`try_closes` 里有、但地址落在被丢掉的区间里），`try` 体越界读进 handler。
* `break_in_try` / `for_else_break`（3.10–3.15）：`break` 被读成 `return`，
  3.12/3.13 把循环出口的块直接接在 `break` 路径上。
* `for_else`（全版本）：源码里的 `for … else` 没有 `break` 时与「循环之后的语句」
  在字节码上同形，信息不在流水里，属于原理上不可判。

---

## 2026-11-04 boom.py 修复 3.10（U/V/W/X）

3.10 剩下 14 行差异，拆开是四处独立缺陷：

| # | 缺陷 | 影响版本 | 根因 / 修法 |
|---|------|----------|-------------|
| U | 跳回 `for` 循环头的 `continue` 认不出来 | 3.10 | `dis` 把跳转目标报成地址，而目标那条指令带 `EXTENDED_ARG` 前缀时，报的是**前缀**的地址。前缀被合并掉之后，这个地址再没有指令承载，reader 只能退回「取地址之上的第一条指令」——3.10 的 reader 匹配的是 `for` 循环头的偏移，于是差了两字节，认不出来。3.9 早就把这种目标转发到下一条还活着的指令（`_resolve_extended_targets`），3.10 现在同样处理 |
| V | `with` 的 `__exit__(None, None, None)` 收尾副本被读成语句 | 3.9、3.10 | `break`/`continue`/`return` 提前退出 `with` 时，编译器在跳转前**另写一份**收尾调用，那份不经过 handler。副本的形状很好认：三个 `None` 是压栈来的，可调用对象是 `DUP_TOP` 复制来的，从不是加载来的。新增 `_hide_teardown_copies` 把这种副本登记为已处理 |
| W | handler 子句结尾的出口没有被读成出口 | 3.9、3.10–3.15 | handler 正文与子句末尾之间的窗口里装的是编译器自己的卸栈（子句副本、`with` 收尾）加出口，源码级的只有出口。现在把窗口登记为已处理，只发那条跳转。窗口里只有出口一条时，那是子句自然落到循环回边上，不是子句自己的出口，仍旧不读 |
| X | 出口只在窗口后面还有东西时才算出口 | 3.9、3.10–3.15 | 原判据要求窗口里出口后面还有指令（3.9 在跳转后还写一遍 `e = None; del e`），3.10 不写那一遍，出口就是窗口最后一条，于是 `except … as e:` 末尾的 `continue` 被丢掉。判据改成「窗口里除了出口还有别的东西」（`EXTENDED_ARG` 前缀不算） |

U/V/W/X 落地后：**3.10 的 `boom.py` 按 AST 逐字一致**，3.9 仍逐字一致；
**ROUND-TRIP 263/263、CONTROL FLOW 77/77 全绿不变**，`prime` 仍是 12 行差异。

W 试过先按「窗口后面还有东西」放宽，3.11 的 `deep_finally` 与
`except_as_nested_finally` 会回退成错（窗口里那条回边被当成子句的 `continue`），
故按 X 的判据收紧。3.11–3.15 未套用 W/X 的传递式出口判定（`_leads_to_escape`），
因为那一版在 3.11 上有回退。

---

## 2026-11-04 boom.py 修 3.11（Y/Z）

3.11 的 `for` 循环整段塌成 `while True:`，内层 `try/except/finally` 丢失，`with`
的 `__exit__` 收尾副本被读成语句。定位到两处：

| # | 缺陷 | 影响版本 | 根因 / 修法 |
|---|------|----------|-------------|
| Y | 跳回 `for` 循环头的 `continue` 认不出来，循环被读成 `while True:` | 3.11–3.15 | 3.11+ 把跳转目标带 `EXTENDED_ARG` 前缀的**前缀地址**留在流水里，而跳转瞄准的正是那个前缀。reader 记的循环头是 `FOR_ITER` 自己的地址，两者对不上；扫「`while True` 回边」时又先撞上前缀，当成了循环头。新增 `_loop_head_offset`：循环头算前缀的地址（3.9/3.10 没有前缀，是空操作） |
| Z | `with` 的 `__exit__` 收尾副本被读成语句 | 3.11–3.15 | 3.9/3.10 的收尾是 `LOAD_CONST None; DUP_TOP; DUP_TOP; CALL_FUNCTION 3; POP_TOP`（可调用对象复制上栈），3.11+ 是 `LOAD_CONST None` ×3 加 `CALL_FUNCTION 2`（可调用对象已在栈上）。`_is_teardown_copy` 两种写法都认；另外把 `EXTENDED_ARG` 算进卸栈指令集——它只是给后面的指令加宽参数，本身没有意思，跳转前挂着它时扫描会停在它上面，后面的跳转就找不到 |

Y/Z 落地后：3.11 的 `for` 循环读回来了，`with` 收尾副本不再泄漏，
`with_in_for_try` 在 3.11 上也过了；**3.11 的 `boom.py` 由 38 行差异降到 36 行**，
**ROUND-TRIP 263/263、CONTROL FLOW 77/77 全绿不变**。

3.11 剩下的 36 行差异是一处根因：**3.11 布局里 `try` 的收尾 `POP_BLOCK` 只出现在
提前退出的路径上**，正路上没有。3.11 的 `try`/`finally` 不用 3.9 那套块栈，块
只在异常路径上关；于是一个体内有 `break`/`continue` 的 `try`，正路走完没有收尾，
而 `_exception_regions` 找到的是 `break` 路径上那份「退出时的收尾副本」
（`body_pops=[54]`）。reader 的模型是「`try` 体到收尾为止」，于是体被截断在
`break` 那里：内层 `try/except/finally` 落在体外、`finally` 子句找不到（读成
`pass`）、`break` 被读到 `try` 外面，多上下文管理器因此只折成一半。

3.9/3.10 里正路的那份收尾在流水更后面，「取最后一个同层 `POP_BLOCK`」正好取对；
3.11 没有那份，只能取到退出路径上的。**要修得让 `Rewriter` 在正路末尾补一个
收尾**（3.11+ 的 `_place_one_close` 目前按异常表各段的末端安置，退出路径的
那段也被算进去了），或者让 reader 在 3.11+ 布局下改按「内联子句副本的起点」
收尾；两处都动到 `cfg_flow.py` 的区域分析与 `decomp311.py` 的收尾安置，尚未动手。

试过三条捷径，都不成立：

* 把 reader 的 `try` 体末尾改成「内联子句副本的起点」——退出路径上那份副本
  也在体内，reader 会在体内撞见 `POP_BLOCK` 而提前组装 `try`，整个 `try`
  反而消失。
* 把 `Rewriter` 的收尾安置改成取所有同 handler 区间的末端——末段是子句副本
  的保护区，收尾被放到 handler 里，等于没放。
* 让 `Rewriter` 把收尾放在内联子句副本前面（`_finally_copy_start`）——找到的
  副本前面正好是编译器留的 `NOP`，而 `NOP` 这一步不产出指令，收尾的
  `POP_BLOCK` 就跟着一起丢了（`_translate_step` 只在「这一步产出了东西」时
  才补收尾）。

补充几点机制，读代码时用得上：

* reader 跳过体内撞见的 `POP_BLOCK`（`_emit_statements` 里
  `start <= block["instr_start"] < i < block["try_end_idx"]` 那一段），因为它
  假定 `try` 体的收尾是最后一条；3.11 布局里退出路径那份收尾落在体内，
  reader 只能靠「体内撞见就跳过」这条规则把它放过，于是正路上那份收尾
  必须由 `Rewriter` 补出来。
* 3.11 编译器在正路上那份内联子句副本前面留了一个 `NOP`（boom.py 的
  `ultimate_cf_nightmare` 里在偏移 1496），正是 3.9 写 `POP_BLOCK` 的位置。
  收尾就该落在那个 `NOP` 上；但 `_translate_step` 只在「这一步产出了东西」
  时才补 `POP_BLOCK`，`NOP` 恰恰什么都不产出，收尾会跟着一起丢掉。
* 只补收尾还不够：3.11 布局下内联子句副本在正路、退出路径、handler 里各有一
  份，`_trim_finally_tail` 会把与 handler 那份同形的那份丢掉。收尾补对之后，
  reader 要在 `try_end_idx + 1` 处读到子句——那里得确实有子句副本，否则
  `finally` 子句仍然读不出来（3.11 的 `_collect_finally_body` 有从 handler
  取子句的分支，但前提是收尾与 handler 之间没有别的指令）。

也就是说这一处要三处一起改：`Rewriter` 把收尾放到正路那份内联子句副本之前
（`NOP` 那个槽位）、`_translate_step` 允许 `NOP` 作锚点也补收尾、reader 在
3.11+ 布局下按「子句副本的起点」而不是「收尾之后」取子句。三者缺一，3.11 的
`try`/`finally` 都会读歪。

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
