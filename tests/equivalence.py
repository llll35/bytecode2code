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
    0x0E52: "3.15",
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


def _firstlineno_metadata(code):
    """Locate compiler-generated class first-line loads and constants."""
    found = []
    instructions = list(dis.get_instructions(code))
    for index, ins in enumerate(instructions[:-1]):
        following = instructions[index + 1]
        if (
            following.opname == "STORE_NAME"
            and following.argval == "__firstlineno__"
            and ins.opname in ("LOAD_CONST", "LOAD_SMALL_INT")
        ):
            found.append((ins.offset, ins.arg if ins.opname == "LOAD_CONST" else None))
    offsets = {offset for offset, _ in found if offset is not None}
    const_indexes = {const for _, const in found if const is not None}
    return offsets, const_indexes


def _dead_exception_tail_offsets(code, original):
    """Find a trailing exception-unwind stub with no source-level behavior."""
    parser = getattr(dis, "_parse_exception_table", None)
    if parser is None:
        return set()
    returns = [
        index for index, ins in enumerate(original)
        if ins.opname in ("RETURN_VALUE", "RETURN_CONST")
    ]
    if not returns:
        return set()
    tail = original[returns[-1] + 1:]
    if not tail or tail[0].opname != "PUSH_EXC_INFO":
        return set()
    cleanup = {
        "COPY", "SWAP", "POP_TOP", "POP_EXCEPT", "PUSH_EXC_INFO",
        "CLEANUP_THROW", "CALL_INTRINSIC_1", "DUP_TOP", "END_SEND",
        "RERAISE",
    }
    if not any(ins.opname == "RERAISE" for ins in tail):
        return set()
    if any(ins.opname not in cleanup for ins in tail):
        return set()
    tail_offsets = {ins.offset for ins in tail}
    targets = {entry.target for entry in parser(code)}
    if not targets.intersection(tail_offsets):
        return set()
    jump_opcodes = set(dis.hasjabs) | set(dis.hasjrel)
    if any(
        ins.opcode in jump_opcodes
        and isinstance(ins.argval, int)
        and ins.argval in tail_offsets
        for ins in original[:returns[-1] + 1]
    ):
        return set()
    return tail_offsets


def instructions(code) -> List[Tuple[int, str, str]]:
    metadata_offsets, _ = _firstlineno_metadata(code)
    original = list(dis.get_instructions(code))
    dead_tail = _dead_exception_tail_offsets(code, original)
    retained = [
        ins for ins in original
        if ins.opname != "NOP" and ins.offset not in dead_tail
    ]
    indexes = {ins.offset: index for index, ins in enumerate(retained)}
    result = []
    jump_opcodes = set(dis.hasjabs) | set(dis.hasjrel)
    for index, ins in enumerate(retained):
        opname = {
            "LOAD_FAST_BORROW": "LOAD_FAST",
            "LOAD_FAST_MAYBE_NULL": "LOAD_FAST",
            "LOAD_FAST_CHECK": "LOAD_FAST",
        }.get(ins.opname, ins.opname)
        if ins.offset in metadata_offsets:
            argval = "<class-firstlineno>"
        elif ins.opcode in jump_opcodes and isinstance(ins.argval, int):
            argval = "->%s" % indexes.get(ins.argval, "<end>")
        else:
            argval = brief(ins.argval)
        result.append((index, opname, argval))
    return result


def constants(code) -> List[str]:
    _, metadata_indexes = _firstlineno_metadata(code)
    return [
        "<class-firstlineno>" if index in metadata_indexes else brief(value)
        for index, value in enumerate(code.co_consts)
    ]


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
