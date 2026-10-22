"""CPython ``.pyc`` magic numbers and the bytecode version each one belongs to.

A ``.pyc`` header starts with a 4 byte magic number.  The first two bytes
identify the bytecode format; the remaining two bytes encode the interpreter
that produced the file.  Only the format bytes matter for us, because they
decide which interpreter is able to ``marshal.loads`` the payload.
"""

from .errors import UnsupportedVersionError

# magic(2 bytes) -> bytecode version
#
# Every value below was read back from an interpreter in ``embed_python``, so
# none of it is guesswork.  CPython 3.6+ encodes the bytecode format in byte 0
# of the magic number (byte 1 is 0x0d up to 3.13 and 0x0e from 3.14 on).
MAGIC_VERSIONS = {
    b"\x61\x0d": "3.9",   # 3.9.x   -> 610d0d0a
    b"\x6f\x0d": "3.10",  # 3.10.x  -> 6f0d0d0a
    b"\xa7\x0d": "3.11",  # 3.11.x  -> a70d0d0a
    b"\xcb\x0d": "3.12",  # 3.12.x  -> cb0d0d0a
    b"\xf3\x0d": "3.13",  # 3.13.x  -> f30d0d0a
    b"\x2b\x0e": "3.14",  # 3.14.x  -> 2b0e0d0a
}

#: Older bytecode that is recognised well enough to name in an error message.
KNOWN_OLD_VERSIONS = ("3.5", "3.6", "3.7", "3.8")

#: Versions this package knows how to dispatch to an interpreter for.
SUPPORTED_VERSIONS = ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14")

#: Versions for which a full decompiler exists (the rest fall back to a
#: normalized bytecode skeleton).
FULL_DECOMPILE_VERSIONS = ("3.9", "3.10", "3.11", "3.12")


def version_key(version):
    """Return a sortable key for a ``"3.x"`` version string."""
    major, _, minor = version.partition(".")
    try:
        return (int(major), int(minor))
    except ValueError:
        return (0, 0)


def parse_version(text):
    """Parse ``"3.12"``/``"3.12.1"`` into ``"3.12"``.  ``None`` if unusable."""
    if not text:
        return None
    parts = str(text).strip().split(".")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    return "%d.%d" % (int(parts[0]), int(parts[1]))


def magic_key(magic):
    """Normalize a magic number to the two bytes that identify the format."""
    if magic is None or len(magic) < 2:
        return b""
    return bytes(magic[:2])


def version_from_magic(magic):
    """Map the magic number of a ``.pyc`` header to a bytecode version.

    Returns ``None`` when the magic number is not in the static table.
    """
    return MAGIC_VERSIONS.get(magic_key(magic))


def require_version(magic):
    """Same as :func:`version_from_magic` but raises on an unknown magic."""
    version = version_from_magic(magic)
    if version is None:
        shown = magic.hex() if magic else "<empty>"
        raise UnsupportedVersionError(
            "unknown .pyc magic number %s; this package can read %s, or %s "
            "once their interpreters are available"
            % (shown, ", ".join(SUPPORTED_VERSIONS), ", ".join(KNOWN_OLD_VERSIONS))
        )
    if version not in SUPPORTED_VERSIONS:
        raise UnsupportedVersionError(
            "bytecode version %s is recognised but not supported "
            "(supported: %s)" % (version, ", ".join(SUPPORTED_VERSIONS))
        )
    return version
