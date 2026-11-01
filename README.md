# bytecode2code

Turn a CPython `.pyc` file back into source code.

```
python main.py decompile module.pyc
```

`bytecode2code` reads the bytecode of a compiled module and reconstructs the
Python that produced it. It supports CPython 3.9 through 3.15, and every
version has its own self-contained back end -- `py39Decompiler` through
`py315Decompiler`.

## One entry point, one back end per version

A `.pyc` payload can only be decoded by the interpreter that produced it --
`marshal` has no cross-version compatibility. The CLI picks the back end from
the magic number in the header, so you never name the version:

```
python main.py decompile module.pyc     # routes on the file's version
```

Routing picks the right *code*, not the right *interpreter*: the process that
runs the command still has to be able to unmarshal the file. To read a 3.14
`.pyc`, run the command under a 3.14 interpreter. `tests/run.py` does exactly
that fan-out for the whole corpus, and `compile`/`demo` drive the interpreters
in `embed_python/` directly.

### Getting the interpreters

`embed_python/` is **not** tracked in git -- the seven CPython builds, plus the
`.zip` archives they were unpacked from, are ~360 MB.
The runner looks for `embed_python/python-X.Y/python.exe`; populate it by
downloading the official embeddable builds from
<https://www.python.org/downloads/windows/> (3.9 - 3.15) and extracting each
into a folder named after its version:

```
embed_python/
  python-3.9/python.exe
  python-3.10/python.exe
  ...
```

Only `compile`, `demo` and the test gate need them; `decompile` works with the
running interpreter alone, as long as it matches the file. `python main.py
info` reports, per version, whether the back end and the interpreter are both
present.

## Commands

Reading a `.pyc` (the version is detected from the file header):

| Command | Output |
|---------|--------|
| `decompile <file.pyc>` (alias `d`) | source code |
| `dis <file.pyc>` (alias `disassemble`) | native disassembly |
| `header <file.pyc>` | decoded `.pyc` header |

`main.py` also answers `skeleton`, `ir` and `code-info`; they are aliases of
`decompile` kept for compatibility with older invocations.

Producing a `.pyc`:

| Command | Output |
|---------|--------|
| `compile <file.py> [--version X.Y]` | a `.pyc` built by a chosen interpreter |

Project itself:

| Command | Purpose |
|---------|---------|
| `versions`, `info` | back ends and interpreters available per version |
| `selftest` | the cross-version regression suite |
| `demo` | compile a sample with every interpreter and read each one back |

## Layout

```
main.py                 the CLI: routes a .pyc to the back end for its version

py39Decompiler/         the 3.9 back end, and the shape every other one targets
  pyc_parser.py         .pyc header decoding, magic -> version, marshal read
  disassembler.py       instruction decoding, EXTENDED_ARG merging
  decompiler.py         bytecode -> AST -> source (the block-stack reader)
  cfg_flow.py           CFG, dominator tree, exception regions
  errors.py             the exception hierarchy

py310Decompiler/        3.9 reader + decomp_compat.py, which restores the
                        control-flow shapes 3.10's peephole pass moves
py311Decompiler/        3.9 reader + decomp311.py, which back-translates the
py312Decompiler/        zero-cost exception table into a synthetic 3.9
py313Decompiler/        block-stack stream (SETUP_FINALLY / POP_BLOCK /
py314Decompiler/        POP_EXCEPT / RERAISE) before the reader ever runs
py315Decompiler/

tests/
  run.py                the gate: round-trip corpus + control-flow probes
  cases.py              the corpus and the probes
  equivalence.py        source comparison and `.pyc` version detection
  samples/              .pyc fixtures (tracked: they need the exact compiler)
  selftest.py           cross-version suite driven by main.py
  test_cfg.py           CFG / Rewriter / output-normalisation units
  repro/                one-off reproduction inputs

embed_python/           the seven CPython interpreters (not tracked)
old/                    superseded frameworks, kept for reference
```

Each `pyNNDecompiler/` is self-contained on purpose: it imports nothing from
its siblings, so a version can be fixed without disturbing the others. The
cost is that `decompiler.py` exists seven times, and a reader fix has to be
ported **by anchor** to each copy -- never by copying a whole file over another,
because the per-version copies differ in line endings and in which methods they
override.

## How the reconstruction works

The decompiler simulates the stack effect of every instruction and folds the
resulting expressions and statements into an AST, which it then prints. Three
things make that hard, and each has its own module:

* **Operand decoding** -- `disassembler.py` trusts `dis` for the running
  interpreter, because the encoding is not stable across releases (3.11 packs a
  flag into `LOAD_GLOBAL`'s oparg, 3.12 adds the same for `LOAD_ATTR`, and 3.11+
  resolves locals through `co_localsplusnames`).
* **Version differences** -- 3.9 marks blocks with a runtime block stack, which
  makes a `try`/`except`/`finally` readable as a range plus a handler address.
  3.11 replaced that with `co_exceptiontable`, so `decomp311.py` rewrites the
  table back into the 3.9 stream, keeping the original byte offsets so jump
  targets stay valid. `decomp_compat.py` does the same job for the shapes 3.10
  moved.
* **State isolation** -- each code object is decompiled with fresh
  reconstruction state, so a nested function does not inherit the enclosing
  scope's bookkeeping.

`cfg_flow.py` is the parallel attempt at the same problem: it answers block
boundaries from a real CFG and dominator tree instead of a forward scan, and
`tests/test_cfg.py` checks it. The recurring control-flow defects this project
has collected are all boundary questions -- a `POP_BLOCK` belonging to an
enclosing `with`, a back edge that is also a `continue`, a `finally` handler
that is really a bare `except`. `bugs.md` records each one with its root cause.

## Running the tests

```
python main.py selftest                  # cross-version regression suite
embed_python/python-3.9/python.exe tests/run.py
```

`tests/run.py` reads `.pyc` samples, and `marshal` has no cross-version
compatibility, so it groups the samples by the version in their header and runs
each group under the matching interpreter in `embed_python/`. The source-only
probes are round-tripped at every version, since they are the only corpus that
reaches each back end.

The embedded distributions do not put the working directory on `sys.path`, so
`-m tests.run` fails inside them -- run the script path, as above. To repeat one
version group only:

```
BYTECODE2CODE_TESTS_GROUP=3.10 BYTECODE2CODE_TESTS_OUT=results.json \
  embed_python/python-3.10/python.exe tests/run.py
```

The report has two halves. **ROUND-TRIP** recompiles the recovered source and
diffs the two disassemblies; **CONTROL FLOW** is the block-boundary corpus, the
stricter gate. Both are tracked in the tables at the top of `bugs.md`.

## Limitations

Recovering source from bytecode is a best-effort reconstruction. The following
are known to be imperfect; each is covered by a test or an allow-list in
`tests/selftest.py`:

* **Control flow inside `try`/`finally` loops.** A `break` or `continue` that
  leaves a `try` body is not yet recovered on every version, and a `return`
  inside a `try`/`finally` is only recovered when the body is otherwise empty.
* **Round-trip coverage.** 234 of 263 round-trips pass; the remainder are
  listed per version in `bugs.md`.
* **Stringified annotations.** `from __future__ import annotations` stores
  annotations as source text, which is recovered by re-parsing.
* **Unreachable code.** Statements the compiler proved dead are not in the
  `.pyc`, so they cannot be recovered.

## License

MIT.
