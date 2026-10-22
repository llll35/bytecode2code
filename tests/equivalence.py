"""Structural comparison of two code objects.

The instruction stream alone is not enough: a function docstring emits no
instruction at all and only lives in ``co_consts[0]``, so a purely
instruction-based check reports a lossy decompilation as identical.  The
constant payload is therefore compared as well.

Nested code objects are paired by their position in a pre-order walk instead
of by name, so same-named siblings -- several ``<lambda>``s in one module, for
instance -- cannot mask each other.
"""

import dis
import os
import struct
from typing import Any, Iterator, List, Optional, Tuple

MAX_REPR = 40

#: low two bytes of a magic number -> CPython version
_MAGIC_VERSIONS = {
    0x0C33: "3.3", 0x0C34: "3.4", 0x0C35: "3.5", 0x0C36: "3.6",
    0x0D33: "3.7", 0x0D41: "3.8", 0x0D61: "3.9", 0x0D6F: "3.10",
    0x0DA7: "3.11", 0x0DCB: "3.12", 0x0DF3: "3.13", 0x0E2B: "3.14",
}


def version_of(path: str) -> Optional[str]:
    """Bytecode version a ``.pyc`` was written for, read from its header."""
    with open(path, "rb") as handle:
        magic = struct.unpack_from("<I", handle.read(4))[0]
    return _MAGIC_VERSIONS.get(magic & 0xFFFF)


def brief(value: Any) -> str:
    """Render a constant or argument compactly enough to diff by eye."""
    if hasattr(value, "co_code"):
        return "<code %s>" % value.co_name
    if isinstance(value, str) and len(value) > MAX_REPR:
        return "<str %r>" % value[:MAX_REPR]
    return repr(value)


def instructions(code) -> List[Tuple[int, str, str]]:
    return [
        (ins.offset, ins.opname, brief(ins.argval))
        for ins in dis.get_instructions(code)
    ]


def constants(code) -> List[str]:
    return [brief(k) for k in code.co_consts]


def walk(code, path: str = "<module>") -> Iterator[Tuple[str, Any]]:
    """Pre-order walk over ``code`` and every nested code object."""
    yield path, code
    for const in code.co_consts:
        if hasattr(const, "co_code"):
            yield from walk(const, "%s.%s" % (path, const.co_name))


def first_difference(left: list, right: list) -> str:
    for i in range(max(len(left), len(right))):
        lv = left[i] if i < len(left) else "<missing>"
        rv = right[i] if i < len(right) else "<missing>"
        if lv != rv:
            return "idx %d: %s vs %s" % (i, lv, rv)
    return "?"


def _differences(expected, actual, path: str) -> List[str]:
    diffs: List[str] = []
    for label, extract in (
        ("bytecode", instructions),
        ("consts", constants),
        ("names", lambda c: list(c.co_names)),
        ("varnames", lambda c: list(c.co_varnames)),
    ):
        want, got = extract(expected), extract(actual)
        if want != got:
            diffs.append("%s %s: %s" % (path, label, first_difference(want, got)))
    return diffs


def compare(expected, actual, path: str = "<module>") -> List[str]:
    """Return human-readable differences; an empty list means equivalent."""
    left = list(walk(expected))
    right = list(walk(actual))

    diffs: List[str] = []
    if len(left) != len(right):
        diffs.append(
            "%s: %d code objects, expected %d" % (path, len(right), len(left))
        )
    for (left_path, left_code), (_, right_code) in zip(left, right):
        diffs.extend(_differences(left_code, right_code, left_path))

    return diffs
