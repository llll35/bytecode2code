# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- 3.11-3.15: a `finally` block's setup is no longer promoted across an
  unrelated `try` statement. `Rewriter._region_start` required only equal
  exception-table depth and handler-address ordering, which are not a nesting
  relation, so the enclosing `finally` opened inside the previous `try`'s
  body; the reader then read that clause's `continue` as a `break` and
  swallowed the loop's `else` and the trailing `try/finally` whole.
  Promotion now also walks the table's protection chain from the candidate
  handler to the proposed enclosing one. `boom.py` AST diff: 3.12/3.13 80 ->
  65 lines, 3.14/3.15 42 -> 15 lines; 3.11 unchanged at 36 (it does not
  promote on this sample) and the gate stays 340/340.

- 3.11-3.15: a `with` that ends a loop body no longer hides the loop's `else`
  clause and the code after the loop. `Decompiler310._process_with` marked the
  span from the teardown to the handler consumed to hide 3.10's duplicated
  post-block code, but with no such duplicate present that span is real source;
  the hide is now skipped when the run past the teardown is an unconditional
  jump back to before the `with` setup (an enclosing loop back edge).
- 3.11-3.15: a `continue` inside `except ... as e` (or any block with a
  `finally`) is no longer read as `break`. 3.11+ compiles it as a forward jump
  to the clause copy on the exit path, which then jumps back to the loop head;
  `_classify_jump` now follows that landing run to its own jump and recovers
  the `continue` when it aims at the innermost head. Together these make
  `boom.py` byte-identical on 3.14 and 3.15; the gate stays 340/340.

- 3.11: a nested `with a as x, b as y:` no longer collapses to a single `with`.
  `Rewriter._analyse_with` anchored the outer block's close at the last
  reachable `__exit__` range, which could be the outer manager's `__exit__` run
  while the nested block unwinds (reachable because the nested handler's normal
  exit jumps to it). Ranges beginning at or after another `with` handler's head
  are now excluded as unwind tail, so the outer close lands at the body's own
  `__exit__`. `boom.py` 3.11 AST diff 36 -> 33 lines; gate stays green.

- 3.12/3.13: a nested `with` body no longer collapses to `continue` with the
  try read outside the loop. `Rewriter._analyse_exception_loop_exits` registered
  any exception-region end landing on a NOP as a loop break, including the
  inner `with`'s normal-path close anchor; the synthetic exit jump then swallowed
  the `POP_BLOCK` the `with` needs. Registration now skips anchors already in
  `with_closes`. `boom.py` 3.12/3.13 AST diff 65 -> 53 lines; gate stays green.

* **A `for` loop was read as a `while True:` on 3.11-3.15** -- 3.11+ leaves the
  `EXTENDED_ARG` prefix a jump names in the stream, and the jump names the
  prefix rather than the instruction behind it, so the loop head the reader
  remembered and the address a back edge aims at were two bytes apart. The
  head of a loop is the prefix's address now, and the scan for a `while
  True:` back edge looks past the prefix before it takes the head for one.
* **The copies of a `with`'s teardown that an early exit writes were read as
  statements** -- 3.9 and 3.10 spell the teardown `LOAD_CONST None;
  DUP_TOP; DUP_TOP; CALL_FUNCTION 3; POP_TOP` (the callable is duplicated
  onto the stack), 3.11 and later spell it three `LOAD_CONST None` over
  `CALL_FUNCTION 2` (the callable is already on the stack). Both shapes are
  recognised now.
* **`boom.py` decompiled to something else than its source on 3.10** -- four
  separate causes, all in the 3.9/3.10 reader and the 3.10 disassembler:
  a branch that names a merged `EXTENDED_ARG` names an address no instruction
  carries, so the `continue` back to the loop head was not recognised (3.9
  already forwarded such a target to the next surviving instruction, 3.10 now
  does the same); the copies of a `with`'s `__exit__(None, None, None)`
  teardown that an early exit writes were read as statements; the window
  between a handler's body and the end of the clause holds the compiler's own
  unwinding -- the copies of the clauses of the blocks the handler sits in --
  and the exit, so the window is marked as handled and only the exit is
  emitted; and that exit was only recognised when the window held something
  behind it. `boom.py` is now AST-identical to its source on 3.10, and 3.9
  still is.
* **A jump back to a `for` loop's head was read as the back edge of a
  `while True:`** -- when the reader could not name the loop (the loop stack
  was empty at that point), the jump was handed to the `while True` reader,
  which did not check that the head it landed on was a `FOR_ITER`. The `for`
  loop's body was then read a second time, inside itself, and on 3.12/3.13 the
  `boom.py` sample died with `RecursionError: maximum recursion depth
  exceeded`. A jump to a `FOR_ITER`/`GET_ITER` head is a `continue` into that
  loop now, never the start of a second loop.
* **The inline copy of a `finally` clause inside a loop body was moved out of
  the loop on 3.11-3.15** -- the search for a tail stranded in front of a
  handler decided that a run was part of the loop body only when the run
  itself jumped back to the loop head. An inlined `finally` at the merge point
  jumps to the copy of the clause behind it, and that copy is what ends the
  loop, so the run was taken for the code behind the loop and moved -- and a
  `try`/`except`/`finally` inside a `for` was read twice. The flow out of the
  run is followed now.
* **A tail re-emitted at its merge point brought back instructions that had
  been dropped for another reason on 3.11-3.15** -- the pop 3.13 writes behind
  an `END_FOR` is dropped, and re-emitting the tail past the handlers undid
  that drop, so the pop showed up as a statement of its own. Only the offsets
  the tail itself drops are resurrected now.
* **A `continue` written inside a `try` that sits inside a `with` was read as
  the clause's copy followed by a statement** -- the compiler emits the copy of
  the `finally` clause, then the `with`'s own teardown, and only then the jump
  back to the loop head. The copy was recognised, but the exit behind the
  teardown was not looked for, so the copy was read as a statement of the
  body. The unwind is stepped over before the jump is looked for now.
* **A `try` inside a `with` was lost on every version** -- the `try`'s
  `POP_BLOCK` sits right in front of the `with`'s own, and the search for the
  block's end took the outer one, so the whole `try` statement disappeared.
  The close that is followed by another close now belongs to the inner block.
* **A `with` swallowed the `return` that follows it on 3.11/3.12** -- the
  synthesised `POP_BLOCK` replaced the first operand of the implicit
  `__exit__(None, None, None)` call, so the call was one argument short and
  the reader's stack model ended up with a leftover. The operand stays now.
* **A `with` claimed the `return` of the `try` around it on 3.11/3.12** -- the
  search for the end of the teardown stepped over the enclosing block's
  `POP_BLOCK` and landed on the `try` body's return value. It stops at the
  block close now, unless the `with` body left a value behind -- then the
  `return` does belong to the `with`.
* **A `with` produced a spurious `while True:` on 3.12** -- when the body
  computes its return value, 3.12 ends the `with` handler with a jump back to
  the code behind the block, which the reader read as a loop's back edge. The
  handler is dropped now.
* **A `with` at the end of a loop body produced a spurious `continue`** -- the
  jump behind the teardown is the loop's own back edge, but a `continue`
  written in the body compiles to the same jump. Only an empty body tells the
  two apart, because a `continue` leaves the body at once.
* **`try`/`finally` decompiled as `try`/`except`/`else` on 3.11/3.12** -- the
  handler analysis rewrote every handler that had no type test into the three
  `POP_TOP`s of a 3.9 bare `except`, but a `finally` handler has no type test
  either. The clause was read as the `except` body and its inline copy as the
  `else` clause, and a nested `try`/`finally` crashed the decompiler outright
  (`produced no statements from 6 instructions`). Handlers are now classified:
  a `finally` handler (runs the clause, then re-raises) is left alone, a bare
  `except` (a `POP_TOP` right behind the `PUSH_EXC_INFO`) keeps the triple pop,
  and a `with` handler (`WITH_EXCEPT_START`) is recognised as well.
* **A method call whose argument is itself a method call lost its receiver on
  3.11/3.12** -- `f.write('\n'.join(results))` decompiled to
  `('\n'.join(results))`. The loader analysis kept a single pending depth, so
  the inner loader reset it and the outer `CALL` was never recognised as the
  loader's call. Each pending loader now keeps its own depth, and every pushed
  value counts against all of them.
* **`except ... as e: return X` lost the `return` on 3.11/3.12** -- the
  synthesised `SETUP_FINALLY` for the implicit `e = None; del e` cleanup
  pointed at the rotation in front of it rather than at the cleanup handler, so
  the reader never saw the `return` that follows the handler's body.
* **Block closes were dropped on 3.11/3.12** -- the opcodes that are translated
  by a branch of their own (`SWAP`, `BINARY_OP`, `BINARY_SLICE`, ...) returned
  before the code that appends the `POP_BLOCK` closing the protected range, so
  the range of a `try` or the implicit `except ... as e` block came out wrong.
  The close is now appended by the caller, which every branch goes through.
* **The code after a `try` statement was swallowed by its `else` clause on
  3.12** -- 3.12 parks the `else` clause inline and lets the handler jump back
  to the code that follows the whole `try`; nothing marks where the clause
  stops. The tail is now moved past the handler along with the jump that
  reaches it, which restores the boundary. This also fixes module-level code,
  where the tail used to be read as a `<code object ...>` assignment.
* **A `return` at the end of a `try` body disappeared** -- the compiler puts
  the `POP_BLOCK` *before* the value of such a return, because a constant needs
  no computing, so the value was pushed after the block closed and the reader
  never saw it. `try: g(p); return 1` lost the whole statement. The value is
  now read from behind the block pop.
* **A `try` inside a `with` gained a `return None` on 3.10** -- 3.10 parks a
  `with` block's handler *after* the close of the `try` that contains it, and
  the handler closes the `with` block a second time; that second close was
  taken for the end of the `try` body.
* **Two-argument slices on 3.12 lost their operands** -- 3.12 folded
  `BUILD_SLICE 2` plus the subscript that consumes it into a single
  `BINARY_SLICE` / `STORE_SLICE` opcode, and `decomp311` had no handler for
  either. The container and both bounds were dropped, so `s[i:j]` decompiled to
  whatever happened to be on the stack -- usually `None`, which turned
  `return s[-n:] if cond else s` into `if cond: return None`. Both opcodes are
  now unfolded back into `BUILD_SLICE 2` + `BINARY_SUBSCR` / `STORE_SUBSCR`.
* **Method calls with a call in their arguments were dropped on 3.11/3.12** --
  `d.append(str(x))` decompiled to `(str(x))`, losing the receiver and the
  method; inside a loop it also produced a stray `x = d`. The method-loader
  analysis gave up as soon as it met the inner `CALL`, so the outer `CALL` was
  never recognised as the loader's call. It now keeps tracking the stack depth
  across the nested call, using the combined `-(argc + 1)` effect of 3.11's
  `PRECALL`/`CALL` pair.
* **A standalone `try: return X` / `finally: C` was flattened on 3.11/3.12** --
  the protected range is empty, so CPython records only the clause's cleanup
  entry and the `try` left no trace; `C` was emitted twice as straight-line
  code and the `return` was left outside. The block is now recovered from the
  inline copy of the clause. `finally: pass` is deliberately not recovered:
  the clause cannot change behaviour, so the exit is left as plain code.
* **A nested `try: return X` / `finally: C` collapsed into its enclosing
  `try`** -- same empty-protected-range shape one level down. Recovered from
  the clause copy inside the handler, gated to a single enclosing block: a
  deeper chain rewrites the intermediate handlers' `PUSH_EXC_INFO` to
  `POP_TOP`, and synthesising those `SETUP_FINALLY` targets over-nests instead
  of reconstructing the source.
* **`LOAD_ATTR` / `LOAD_GLOBAL` decoding on 3.11/3.12** -- the hand-rolled
  operand decoder indexed `co_names` directly, which is wrong once the opcode
  packs a flag bit into the low bits of its oparg. It read the wrong name and
  raised `IndexError` as soon as the oparg exceeded `len(co_names) / 2`. The
  disassembler now trusts `dis` for the running interpreter.
* **Non-ASCII output corruption in `pyvers`** -- the worker wrote its response
  through the console encoding (GBK on Chinese Windows) while the host read it
  back as UTF-8, turning every non-ASCII character of the decompiled source
  into `U+FFFD` with no error. The worker now writes UTF-8 bytes.
* **`pyvers.decomp311` / `pyvers.decomp_compat` were not importable** -- both
  used flat imports, so `import pyvers.decomp311` failed and the worker loaded
  a second, private copy of every module.
* **`tests/run.py` could not run** -- the `.pyc` corpus is not one version
  (`checkerboard`, `py39_syntax_demo` and `feature_matrix` are 3.9, `prime` is
  3.12) and `marshal` has no cross-version compatibility, so whichever
  interpreter the runner picked, the other version's samples raised
  `ValueError: bad marshal data`. The runner now groups the samples by the
  version in their header, runs each group under the matching embedded
  interpreter, and recompiles the result with that same interpreter. It also
  round-trips the source-only probes at every version, and decompiles each
  sample with the back end that matches its bytecode instead of always using
  the 3.9 reader.
* **`pyc_parser` magic table never matched a real file** -- `parse` read a
  four-byte magic while the table was keyed on two, and the "populate for every
  minor version" loop overwrote the same key 29 times. It reported `3.29` for
  the running interpreter and `unknown-0x…` for everything else. The table is
  now keyed on the two format bytes and covers 1.5 - 3.14.
* **`del a[0]` and `del a.b` were dropped** -- there were no handlers for
  `DELETE_SUBSCR` / `DELETE_ATTR`.
* **`assert cond, msg` became `if not cond: raise msg`** -- a statement that
  raises a *string* and dies with `TypeError`. Reconstructed from the
  jump-over-raise the compiler emits.
* **`class C(Base, metaclass=M)` produced invalid syntax** -- the
  `__build_class__` special case only covered positional calls, so a class with
  keywords leaked its body as a bare code-object constant.
* **`a = b = 1` became `b = (a := 1)`** -- any `DUP_TOP` followed by a store was
  read as a walrus operator. The number of stores now decides.
* **`*a, b = x` lost the star** -- `UNPACK_EX` had no handler, so the starred
  target was silently dropped.
* **Relative imports were rewritten as absolute** -- `from ..pkg.mod import y`
  lost its dot count, and `from . import x` was dropped entirely.
* **Chained comparisons of four or more links were re-associated** --
  `a < b < c < d` became `((a < b) < c) < d`, a different expression, and the
  last links were dropped.
* **A nested code object inherited the enclosing scope's bookkeeping** --
  `_imported_modules` and `_handled_ranges` leaked across code objects, deleting
  a nested function's `import` statements.
* **A `try` inside a loop absorbed the following code as an `else` clause** --
  the body's jump out of the loop was mistaken for the jump over a handler.
* **A stray `raise` was emitted inside `try` bodies** -- the compiler closes
  every `except` chain with a bare `RERAISE`, which has no source form.
* **A `return` inside `except X as e:` was lost** -- the clause's exit sequence
  sits behind the compiler's own `e = None; del e` cleanup, which was skipped
  wholesale.
* **A `return` as the last statement of an empty `try`/`finally` body was left
  outside the `try`** -- it is compiled after the inline finally copy.
* **`while True: try: break: finally:` crashed the worker** --
  `_classify_jump` coerced a non-jump instruction's `argval` (a variable name)
  to an `int`.
* **`a = b = 1` on 3.11/3.12 became `b, a = (1, 1)`** -- the back-translator
  read a run of stores after a `COPY 1` as a parallel assignment.
* **`s[::-1]` printed as `s[None::-1]`** -- an omitted slice bound reached the
  decompiler as `LOAD_CONST None`.
* **`tests/selftest_310plus.py` never ran** -- it called `os.chdir` with the
  author's absolute path, and then `-m tests.selftest` inside the embedded
  interpreters, which do not put the working directory on `sys.path`, so every
  version raised `ModuleNotFoundError: No module named 'tests'`. The launcher
  captured stdout only, so the cause was discarded and each version printed
  `FAILED (exit 1)` while `python -m tests.selftest --all` stayed green. It now
  derives the repository root from `__file__`, runs `tests/selftest.py` by
  script path, prints the child's stderr on failure and takes the versions to
  run as arguments: 3.10-3.14 report 2/2 and 3.15 3/3.
* **A branch aimed at a re-emitted tail resolved onto the handler in front of it**
  -- the reader took the first instruction at or after the jump's address, but the
  tail a merge point re-emits is laid out behind the handler that was compiled in
  front of it, so an instruction that merely follows the address can be listed
  before the one carrying it. A run that holds the address exactly is now preferred
  and the higher one is only the fallback -- this is what truncated `main` in the
  3.12 `prime` sample.
* **The duplicated `return None` epilogues of 3.11+ left their branches dangling**
  -- folding the copies a handler region repeats deleted them in place, so a branch
  that skipped to one named an address no instruction carries. Each deleted address
  is now recorded with the copy that stays and the branches aimed at it are
  re-aimed, which is how 3.9 wrote it: one epilogue that both the body and the
  clauses reach.
* **A method call whose argument is an inlined comprehension lost its receiver on
  3.12+** -- `"".join([c for c in x])` decompiled to `([c for c in x])`. The call
  classification measured the stack against the raw inlined loop, which
  `_lift_comprehension` later replaces with a single call, so the pending loader
  never recognised its own `CALL`. The whole run and the bookkeeping that returns
  the borrowed locals are skipped now.
* **A function's explicit trailing `return None` could not survive the epilogue
  folding on 3.11** -- a `JUMP_FORWARD` into the epilogue is the only trace a
  source-level `return` leaves, and an AST-level rule that dropped every trailing
  bare `return` erased it along with the genuine ones. The reader now decides at
  the instruction stream: the pair counts as the implicit epilogue when the walk
  reaches it at the end of the body, whether or not handler code is still listed
  behind it. ROUND-TRIP 262/263 → **263/263**.
* **`boom.py` exploded on 3.9** -- the stray-tail re-linearisation added for 3.12
  also ran on genuine 3.9/3.10 streams, where a `SETUP_FINALLY` names the inlined
  clause rather than an out-of-line handler, so it cut a `try` in half and
  duplicated every `finally`. The move is behind a class flag now
  (`HOIST_STRAY_BLOCK_TAILS`, off in the base reader, on only for the
  back-translated 3.11+ view) and 3.9 round-trips `boom.py` to an identical AST.
* **Every function grew a phantom docstring on 3.14/3.15** -- those versions no
  longer reserve `co_consts[0]` for the docstring, so the first constant the body
  uses sits in that slot and a string there was pasted back as a docstring
  (`"""stop"""` over and over). A docstring is the one constant the body never
  loads, so a `LOAD_CONST` of the slot now suppresses the recovery.
* **A function ending in an `if` repeated its implicit `return None` inside the
  body on 3.10** -- 3.10 writes the epilogue once per branch, and the pair that
  closed the branch was only recognised when it ended the stream. Two pairs in a
  row at the end are one epilogue seen twice.
* **`with` teardown leaked as `None(None, None, None)` on 3.11–3.15** -- a
  `break`/`continue` leaving a `with` body runs the manager's `__exit__` on the
  way out, and 3.11+ pastes a copy of that call behind every such exit. Only the
  body's own falling-out copy was folded, so the loop-exit copies showed up as a
  literal `None(...)` call. `Rewriter._drop_with_unwind_teardowns` drops them,
  keyed off the exception table pinning the run to a `with` handler plus the
  operands being preceded by a statement completion rather than a callable load
  (which is what a real `foo(None, None, None)` always pushes first).
* **`boom.py` collapsed to a 4-line stub on 3.14/3.15** -- 3.14's `with` collapse
  leaves one `POP_BLOCK` for both `SETUP_WITH`s, so the CFG block-stack walk
  credits a `SETUP_WITH` -- and a `try` read inside its body -- a close that lies
  past the body being read, and the reader dropped everything after the first
  `if …: continue`. `_find_pop_block` now checks a `with` close is followed by
  its `__exit__` teardown before trusting the graph, and takes a `limit` (the
  enclosing body's end) to re-derive the close by a clamped scan. `with` bodies
  with an interleaved `finally` read in full again. ROUND-TRIP **263/263**,
  CONTROL FLOW **77/77** unchanged.

### Added

* `README.md`, `pyproject.toml`, `.gitignore`, `CHANGELOG.md` and a GitHub
  Actions workflow.
* `bytecode2code/errors.py` -- a single exception hierarchy
  (`Bytecode2CodeError` → `PYCError` / `UnsupportedBytecodeError` /
  `DecompilationError`) so callers can tell an unreadable file from a malformed
  one from a bug.
* `bytecode2code/__main__.py` -- `python -m bytecode2code` now works.
* Regression probes for `del`, `assert`, class keywords, chained assignment,
  starred unpacking, relative imports, long chains, nested-scope isolation,
  exception handling and `return` inside `try`/`finally`.
* More regression probes: a `return` at the end of a `try` body, a method call
  whose argument is itself a method call, and a `finally` clause next to a
  nested `try` -- all three are checked against the source's own AST on every
  supported version.

### Changed

* The CLI turns the package's own errors into a one-line message and a non-zero
  status; a traceback is reserved for actual bugs.
* The root directory was tidied: the one-off `_d1_*.py` / `_debug_*.py` scripts
  moved into `debug/archive/`.
* The repository itself was tidied, with no change to any decompiler's
  behaviour (the gate still reports 234/263 round-trips and 77/77 control
  flows). `.gitignore` declared `embed_python/`, `debug/`, `_scratch/`,
  `__pycache__/` and the local tooling directories ignored, but 9,815 of their
  files were still tracked; they are out of the index now, so the tree tracks
  112 files instead of 9,961 and `embed_python/` is genuinely the
  download-on-demand directory the README describes. `_scratch/` is ignored in
  full, not just its text output.
* `README.md` described the removed `bytecode2code/` + `pyvers/` front ends and
  claimed 3.13 and 3.14 produced only a normalised disassembly. It now matches
  the seven `pyNNDecompiler/` back ends, records that `skeleton`, `ir` and
  `code-info` are aliases of `decompile`, and documents how to run the gate
  under the embedded interpreters.

### Removed

* The superseded back ends `FixedDecompiler39/` and `py311_x` moved to `old/`,
  where the archived `pyvers/` already lived; no live module imported them.
* The scripts that overwrote a whole backend with one file (`apply_fix3.py`,
  `apply_fixed39.py`, `fix2.py`, `fix_fixed.py`, `propagate_*.py`) -- the
  per-version copies have diverged too much for that since, and the rule is now
  to port reader fixes by anchor.
* `independent_control_flow/` in its entirety. `py310Decompiler` through
  `py315Decompiler` each carried a byte-identical copy of a placeholder engine
  that nothing imported; the 3.9 copy was on the live path but was a no-op --
  its `rebuild_try_finally_raise()` dropped statements only when their *text*
  equalled one of three literals copied from a single probe, and it is handed
  `ast.stmt` nodes, so the comparison never matched. Removing the call left the
  gate unchanged (234/263 round-trips, 77/77 control flows).
* Unreferenced scratch files from the root: `tmp.txt`, `awkprof.out`. The
  reproduction inputs moved to `tests/repro/`; `boom.py` and `test_sc.py` stay
  at the root because `bugs.md` refers to them by path.

