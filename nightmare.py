#!/usr/bin/env python3
"""nightmare.py -- a decompiler stress sample that every backend gets wrong.

This is a *reproducer*, not a fix.  It collects source snippets aimed at the
places where the seven back ends (`py39Decompiler` ... `py315Decompiler`) are
still known to lose control flow, and then, for the interpreter running the
script:

1. compiles each snippet,
2. decompiles it with the matching back end,
3. recompiles the result,
4. compares the rebuilt module against the original -- source AST, bytecode,
   constants, names and locals of every nested code object.

A snippet is reported as:

    OK      the round trip is equivalent
    SKIP    the running interpreter cannot parse the snippet
    DIFF    the decompiler returned source that does not round-trip
    CRASH   decompiling or recompiling raised

Every snippet here was chosen because at least one supported version fails it;
most fail several.  Run it on its own with a supported interpreter, or from any
Python to fan the check out to every interpreter under ``embed_python/``:

    python nightmare.py
    python nightmare.py --one            # only the running interpreter
    python nightmare.py --verbose        # print the broken source

The script exits non-zero as soon as one snippet fails, which is the point:
until the defects are fixed this is the "make the project fall over" button,
not part of the green gate.

Known weak spots exercised below (see ``bugs.md``):

* a conditional ``break`` inside ``try``/``finally`` (3.10+),
* ``while True`` + nested ``try``/``finally`` + ``else`` (all versions),
* ``for``/``else`` followed by a trailing ``try``/``finally`` (3.9, 3.10,
  3.14, 3.15),
* nested ``finally`` clauses (3.9, 3.12-3.15),
* ``except ... as e`` with a nested ``finally`` and ``continue`` (several),
* deeply nested ``with`` blocks (all versions, including ``None(...)`` leaks),
* ``match`` statements (3.10+; there is no ``MATCH_*`` reader at all),
* ``except*`` shapes on 3.11+.

No snippet is executed.  The check is structural on purpose: a wrong control
flow graph is exactly what this project exists to avoid, and running the code
would need a fixture for every ``open``/``print`` it mentions.
"""

import ast
import importlib
import os
import subprocess
import sys
import textwrap
import warnings

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SUPPORTED = ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14", "3.15")


# ---------------------------------------------------------------------------
# The sample.  Each entry is (name, minimum version, source).
# ---------------------------------------------------------------------------

def _nested_with(depth):
    lines = ["def nested_with(x):"]
    for level in range(depth):
        lines.append("    " * (level + 1) + "with open('a') as a%d:" % level)
    lines.append("    " * (depth + 1) + "x += 1")
    lines.append("    return x")
    return "\n".join(lines) + "\n"


def _nested_try_finally(depth):
    lines = ["def nested_try_finally(x):"]
    for level in range(depth):
        lines.append("    " * (level + 1) + "try:")
    lines.append("    " * (depth + 1) + "x += 1")
    for level in reversed(range(depth)):
        lines.append("    " * (level + 1) + "finally:")
        lines.append("    " * (level + 2) + "x += 1")
    lines.append("    return x")
    return "\n".join(lines) + "\n"


SNIPPETS = [
    # -- universal syntax (3.9+) -------------------------------------------
    ("while_true_try_finally", "3.9", '''
        def while_true_try_finally(data):
            i = 0
            while True:
                try:
                    if i >= len(data):
                        break
                    try:
                        print(data[i])
                    except IndexError:
                        break
                    finally:
                        i += 1
                finally:
                    print('tick')
            else:
                print('never')
            return i
    '''),
    ("for_else_trailing_finally", "3.9", '''
        def for_else_trailing_finally(data):
            for value in data:
                print(value)
            else:
                print('done')
            try:
                return 1
            finally:
                print('cleanup')
    '''),
    ("conditional_break_in_try", "3.9", '''
        def conditional_break_in_try(x):
            while True:
                try:
                    if x:
                        break
                except ValueError:
                    pass
                finally:
                    print(1)
            return x
    '''),
    ("deep_finally", "3.9", '''
        def deep_finally(x):
            try:
                try:
                    try:
                        return x
                    finally:
                        print('a')
                finally:
                    print('b')
            finally:
                print('c')
    '''),
    ("except_as_nested_finally", "3.9", '''
        def except_as_nested_finally(data):
            out = []
            for value in data:
                try:
                    out.append(int(value))
                except ValueError as error:
                    out.append(str(error))
                    continue
                finally:
                    try:
                        out.append('deep')
                    finally:
                        out.append('deepest')
            else:
                out.append('finished')
            return out
    '''),
    ("nested_with", "3.9", _nested_with(6)),
    ("nested_try_finally", "3.9", _nested_try_finally(8)),
    ("generator_finally", "3.9", '''
        def generator_finally(data):
            for item in data:
                try:
                    yield item
                except GeneratorExit:
                    return
                finally:
                    print(item)
    '''),

    # -- 3.10+ --------------------------------------------------------------
    ("match_basic", "3.10", '''
        def match_basic(x):
            match x:
                case 0:
                    return 'zero'
                case 1 | 2:
                    return 'small'
                case _:
                    return 'other'
    '''),
    ("match_class_and_guard", "3.10", '''
        def match_class_and_guard(value):
            match value:
                case {'a': a, 'b': b} if a > b:
                    return a - b
                case {'a': a, **rest}:
                    return a + len(rest)
                case str() | bytes() as text:
                    return len(text)
                case [first, *tail] if tail:
                    return first
                case _:
                    return None
    '''),
    ("match_module_level", "3.10", '''
        match 1:
            case 1:
                selected = 1
            case _:
                selected = 2
    '''),

    # -- 3.11+ --------------------------------------------------------------
    ("except_star_else", "3.11", '''
        def except_star_else(fn):
            try:
                fn()
            except* ValueError as error:
                print('value', error)
            else:
                print('no error')
    '''),
    ("except_star_finally", "3.11", '''
        def except_star_finally(fn):
            try:
                fn()
            except* ValueError as error:
                print('value', error)
            finally:
                print('finally')
    '''),
    ("except_star_with", "3.11", '''
        def except_star_with(fn):
            with open('a') as handle:
                try:
                    fn(handle)
                except* ValueError as error:
                    print(error)
    '''),
    ("except_star_deep", "3.11", '''
        def except_star_deep(fn):
            try:
                try:
                    try:
                        fn()
                    except* KeyError:
                        print('key')
                except* ValueError:
                    print('value')
            except* TypeError:
                print('type')
            finally:
                print('done')
    '''),
]


# ---------------------------------------------------------------------------
# One interpreter, one snippet.
# ---------------------------------------------------------------------------

def _source(snippet):
    return textwrap.dedent(snippet).lstrip()


def _ast_of(source):
    return ast.dump(ast.parse(source))


def check_snippet(version, name, source, verbose):
    """Return (status, detail) for *name* under *version*."""
    source = _source(source)
    try:
        original = compile(source, "<%s>" % name, "exec")
    except SyntaxError:
        return "SKIP", "the running interpreter cannot parse it"

    backend = importlib.import_module("py%sDecompiler" % version.replace(".", ""))
    try:
        output = backend.decompile(original)
    except Exception as error:  # RecursionError etc. are all failures here
        return "CRASH", "decompile: %s: %s" % (type(error).__name__, error)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rebuilt = compile(output, original.co_filename, "exec")
    except Exception as error:
        return "CRASH", "recompile: %s: %s" % (type(error).__name__, error)

    diffs = []
    try:
        if _ast_of(source) != _ast_of(output):
            diffs.append("source AST differs")
    except SyntaxError as error:
        diffs.append("emitted source does not parse: %s" % error)

    try:
        from tests.equivalence import compare
        diffs.extend(compare(original, rebuilt))
    except Exception as error:
        diffs.append("code comparison failed: %s: %s" % (type(error).__name__, error))

    if not diffs:
        return "OK", ""
    detail = "; ".join(diffs[:4])
    if verbose:
        detail += "\n--- emitted source ---\n" + output
    return "DIFF", detail


# ---------------------------------------------------------------------------
# Running one interpreter / fanning out.
# ---------------------------------------------------------------------------

def run_here(verbose):
    version = "%d.%d" % sys.version_info[:2]
    if version not in SUPPORTED:
        print("Python %s: no in-tree backend for this interpreter" % version)
        return 1

    print("Python %s (%s backend)" % (version, version))
    failures = 0
    checked = 0
    for name, minimum, source in SNIPPETS:
        if (int(version.split(".")[0]), int(version.split(".")[1])) < tuple(
                int(part) for part in minimum.split(".")):
            status, detail = "SKIP", "needs Python %s+" % minimum
        else:
            status, detail = check_snippet(version, name, source, verbose)
        if status == "SKIP":
            print("  [SKIP] %-28s %s" % (name, detail))
            continue
        checked += 1
        if status != "OK":
            failures += 1
        print("  [%s] %-28s %s" % (status, name, detail))

    print("  -> %d/%d snippets round-trip" % (checked - failures, checked))
    return 1 if failures else 0


def _embed_exe(version):
    path = os.path.join(ROOT, "embed_python", "python-" + version, "python.exe")
    return path if os.path.isfile(path) else None


def run_all(verbose):
    interpreters = [(version, _embed_exe(version)) for version in SUPPORTED]
    interpreters = [(version, path) for version, path in interpreters if path]
    if not interpreters:
        return run_here(verbose)

    overall_failures = 0
    print("=" * 72)
    print("NIGHTMARE -- decompiler stress sample across every embedded version")
    print("=" * 72)
    for version, interpreter in interpreters:
        command = [interpreter, os.path.abspath(__file__), "--one"]
        if verbose:
            command.append("--verbose")
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=180,
                encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            print("Python %s: TIMEOUT (decompiler did not finish in 180s)" % version)
            overall_failures += 1
            continue
        text = (completed.stdout or "").rstrip()
        if text:
            print(text)
        if completed.stderr.strip():
            print(completed.stderr.rstrip())
        if completed.returncode != 0:
            overall_failures += 1
        print()

    print("=" * 72)
    if overall_failures:
        print("nightmare: %d of %d interpreter groups failed"
              % (overall_failures, len(interpreters)))
        return 1
    print("nightmare: every group round-tripped (unexpected)")
    return 0


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    verbose = "--verbose" in args or "-v" in args
    if "--one" in args:
        return run_here(verbose)
    return run_all(verbose)


if __name__ == "__main__":
    sys.exit(main())
