# bytecode2code

Turn a CPython `.pyc` file back into source code.

```
python main.py decompile module.pyc
```

`bytecode2code` reads the bytecode of a compiled module and reconstructs the
Python that produced it. It works on every CPython from 3.9 through 3.14, and
decompiles 3.9 - 3.12 fully (3.13 and 3.14 fall back to a normalised
disassembly).

## Why two front ends

A `.pyc` payload can only be decoded by the interpreter that produced it --
`marshal` has no cross-version compatibility. The project therefore has two
halves:

| Half | What it does | When it applies |
|------|--------------|-----------------|
| `bytecode2code/` | Decompiles with the interpreter that is *running*. | The interpreter matches the file. |
| `pyvers/` | Routes the file to whichever interpreter in `embed_python/` can decode it, in a subprocess. | Every version. |

`python main.py` is the single entry point that picks between them, so the
caller never has to know which one is needed:

```
python main.py decompile module.pyc        # any version, auto-detected
python -m bytecode2code decompile m.pyc    # same thing, running interpreter only
```

### Getting the interpreters

`embed_python/` is **not** tracked in git -- the six CPython builds are ~313 MB.
`pyvers` looks for `embed_python/python-X.Y/python.exe`; populate it by
downloading the official embeddable builds from
<https://www.python.org/downloads/windows/> (3.9 - 3.14) and extracting each
into a folder named after its version:

```
embed_python/
  python-3.9/python.exe
  python-3.10/python.exe
  ...
```

Point `PYVERS_EMBED_DIR` at a different directory if you keep them elsewhere.
Only `python main.py decompile` needs them; `python -m bytecode2code` uses the
running interpreter alone.

## Commands

Reading a `.pyc` (the version is detected from the file header):

| Command | Output |
|---------|--------|
| `decompile <file.pyc>` (alias `d`) | source code |
| `dis <file.pyc>` (aliases `disassemble`, `dis`) | native disassembly |
| `skeleton <file.pyc>` | version-normalised pseudo source |
| `ir <file.pyc>` | normalised instruction tree (JSON) |
| `code-info <file.pyc>` (alias `infos`) | code object hierarchy (JSON) |
| `header <file.pyc>` | decoded `.pyc` header |
| `info [<file.pyc>]` (alias `i`) | interpreters, or one file's details |

Producing a `.pyc`:

| Command | Output |
|---------|--------|
| `compile <file.py>` | a `.pyc` built by a chosen interpreter |

Project itself:

| Command | Purpose |
|---------|---------|
| `versions` | magic number table and decompile coverage |
| `selftest` | the cross-version regression suite |
| `demo` | compile a sample with every interpreter and read each one back |

## Layout

```
bytecode2code/          the single-interpreter decompiler
  pyc_parser.py         .pyc header decoding and magic -> version
  disassembler.py        instruction decoding
  decompiler.py         bytecode -> AST -> source
  errors.py             the exception hierarchy
  main.py               the CLI

pyvers/                 the cross-version layer
  dispatch.py           host side: writes a request, runs the worker
  worker.py             runs inside the target interpreter
  decomp_compat.py      3.10 control-flow shims over the 3.9 decompiler
  decomp311.py          rewrites 3.11/3.12 bytecode into the 3.9 shape
  normalize.py          version-independent instruction normalisation
  interp.py             discovers the interpreters under embed_python/
  versions.py           magic numbers and supported versions
  selftest.py           the cross-version regression suite

tests/                  round-trip and source-fidelity tests
embed_python/           the CPython interpreters used by pyvers
```

## How the reconstruction works

The decompiler simulates the stack effect of every instruction and folds the
resulting expressions and statements into an AST, which it then prints. Three
things make that hard, and each has its own module:

* **Operand decoding** -- `disassembler.py` trusts `dis` for the running
  interpreter, because the encoding is not stable across releases (3.11 packs a
  flag into `LOAD_GLOBAL`'s oparg, 3.12 adds the same for `LOAD_ATTR`, and 3.11+
  resolves locals through `co_localsplusnames`).
* **Version differences** -- `decomp311.py` back-translates 3.11/3.12 bytecode
  into a fake 3.9 stream, keeping byte offsets so jump targets stay valid, and
  `decomp_compat.py` restores the 3.10 control-flow shapes the 3.9 reader
  expects.
* **State isolation** -- each code object is decompiled with fresh
  reconstruction state, so a nested function does not inherit the enclosing
  scope's bookkeeping.

## Running the tests

```
python -m tests.run          # round-trip + source fidelity
python main.py selftest      # cross-version regression suite
```

`tests/run.py` reads `.pyc` samples, and `marshal` has no cross-version
compatibility, so it groups the samples by the version in their header and runs
each group under the matching interpreter in `embed_python/`. The source-only
probes are round-tripped at every version, since they are the only corpus that
reaches each back end. `selftest.py` compiles a corpus with every interpreter
in `embed_python/` and compares the results.

## Limitations

Recovering source from bytecode is a best-effort reconstruction. The following
are known to be imperfect; each is covered by a test or an allow-list in
`pyvers/selftest.py`:

* **Control flow inside `try`/`finally` loops.** A `break` or `continue` that
  leaves a `try` body is not yet recovered on every version, and a `return`
  inside a `try`/`finally` is only recovered when the body is otherwise empty.
* **3.13/3.14.** Only a normalised disassembly is produced; there is no full
  decompiler for these versions yet.
* **Stringified annotations.** `from __future__ import annotations` stores
  annotations as source text, which is recovered by re-parsing.
* **Unreachable code.** Statements the compiler proved dead are not in the
  `.pyc`, so they cannot be recovered.

## License

MIT.
