"""Source-fidelity report: original source vs decompiled output, at AST level.

Both files are pushed through :func:`ast.unparse` before diffing, so comments,
quote style, blank lines, line breaks and parenthesisation cancel out and only
genuine structural differences remain.

This is a *report*, not a pass/fail gate.  Some differences are provably
unrecoverable -- under ``from __future__ import annotations`` CPython neither
evaluates nor stores a function-local variable annotation, so
``x: T = v`` and ``x = v`` compile to the same code object and nothing in the
``.pyc`` records that ``T`` was ever written down.
"""

import ast
import difflib
import os
import sys
from typing import List, NamedTuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.cases import FILE_SAMPLES, OUTPUTS, SAMPLES


class Report(NamedTuple):
    name: str
    diff: List[str]
    note: str = ""
    """Set when there is nothing to compare, so silence is not mistaken for a pass."""


def _sources(name: str):
    """Pair a sample with its source file, or ``None`` if it ships as ``.pyc`` only."""
    pyc_name = FILE_SAMPLES[name]
    source = os.path.join(SAMPLES, pyc_name[: -len(".pyc")] + ".py")
    if not os.path.exists(source):
        return None
    return source, os.path.join(OUTPUTS, "%s.py" % name)


def report(name: str) -> Report:
    pair = _sources(name)
    if pair is None:
        return Report(name, [], "ships as .pyc only, no source to diff")
    if not os.path.exists(pair[1]):
        return Report(name, [], "not decompiled yet, run the round-trip first")

    source, decompiled = pair
    left = ast.unparse(ast.parse(open(source, encoding="utf-8").read()))
    right = ast.unparse(ast.parse(open(decompiled, encoding="utf-8").read()))

    diff = [
        line
        for line in difflib.unified_diff(
            left.splitlines(), right.splitlines(),
            "source", "decompiled", lineterm="", n=1,
        )
    ]
    return Report(name, diff)


def run() -> List[Report]:
    return [report(name) for name in FILE_SAMPLES]


if __name__ == "__main__":
    for item in run():
        if item.note:
            print("%-24s skipped: %s" % (item.name, item.note))
            continue
        if not item.diff:
            print("%-24s structurally identical" % item.name)
            continue
        print("%-24s %d differing lines" % (item.name, len(item.diff)))
        for line in item.diff:
            print("    " + line)
