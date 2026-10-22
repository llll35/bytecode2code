# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

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
