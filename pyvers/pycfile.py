"""Host side ``.pyc`` header parsing.

Only the fixed size header is decoded here, which is completely version
independent: no ``marshal`` and therefore no requirement that the running
interpreter matches the file.
"""

import datetime
import os
import struct

from .errors import PyversError
from .versions import require_version, version_key

#: ``magic(4) + flags(4) + mtime(4) + size(4)`` for timestamp based files.
HEADER_TIMESTAMP = 16
#: ``magic(4) + flags(4) + hash(8)`` for hash based files.
HEADER_HASH = 16
#: Python 3.3 - 3.6 had no flags word: ``magic(4) + mtime(4) + size(4)``.
HEADER_LEGACY = 12

FLAG_HASH_BASED = 0x01
FLAG_CHECK_SOURCE = 0x02

_HEADER_SIZE = 16


class PYCHeader(object):
    """The fixed size prefix of a ``.pyc`` file."""

    __slots__ = ("path", "magic", "flags", "payload_offset", "size",
                 "timestamp", "source_size", "source_hash", "version")

    def __init__(self, path, magic, flags, payload_offset, size, version):
        self.path = path
        self.magic = magic
        self.flags = flags
        self.payload_offset = payload_offset
        self.size = size
        self.timestamp = None
        self.source_size = None
        self.source_hash = None
        self.version = version

    @property
    def hash_based(self):
        return bool(self.flags & FLAG_HASH_BASED)

    @property
    def check_source(self):
        return bool(self.flags & FLAG_CHECK_SOURCE)

    @property
    def invalidation_mode(self):
        """``"hash"``, ``"checked_hash"``, ``"unchecked_hash"`` or ``"timestamp"``."""
        if not self.hash_based:
            return "timestamp"
        return "checked_hash" if self.check_source else "unchecked_hash"

    def as_dict(self):
        return {
            "path": self.path,
            "magic": self.magic.hex(),
            "version": self.version,
            "flags": self.flags,
            "hash_based": self.hash_based,
            "check_source": self.check_source,
            "invalidation_mode": self.invalidation_mode,
            "payload_offset": self.payload_offset,
            "size": self.size,
            "timestamp": self.timestamp,
            "source_size": self.source_size,
            "source_hash": self.source_hash.hex() if self.source_hash else None,
        }


def read_header(path):
    """Read the header of the ``.pyc`` at *path*."""
    with open(path, "rb") as handle:
        blob = handle.read(_HEADER_SIZE)
    if len(blob) < 8:
        raise PyversError("%s is too small to be a .pyc file" % path)

    magic = blob[:4]
    version = require_version(magic)
    total = os.path.getsize(path)

    if version_key(version) < (3, 7):  # pragma: no cover - legacy bytecode only
        payload_offset = HEADER_LEGACY
        mtime, size = struct.unpack("<II", blob[4:12])
        flags = 0
        header = PYCHeader(path, magic, flags, payload_offset, total, version)
        header.timestamp = mtime
        header.source_size = size
        return header

    flags = struct.unpack("<I", blob[4:8])[0]
    if flags & FLAG_HASH_BASED:
        payload_offset = HEADER_HASH
        source_hash = blob[8:16]
    else:
        payload_offset = HEADER_TIMESTAMP
        mtime, size = struct.unpack("<II", blob[8:16])
        source_hash = None

    header = PYCHeader(path, magic, flags, payload_offset, total, version)
    header.source_hash = source_hash
    if not (flags & FLAG_HASH_BASED):
        header.timestamp = mtime
        header.source_size = size
    return header


def timestamp_text(header):
    """Human readable form of a timestamp based header, or ``""``."""
    if header.timestamp is None:
        return ""
    try:
        stamp = datetime.datetime.fromtimestamp(header.timestamp)
    except (OverflowError, OSError, ValueError):
        return str(header.timestamp)
    return stamp.strftime("%Y-%m-%d %H:%M:%S")


def describe(path):
    """Human readable one block summary of the ``.pyc`` at *path*."""
    header = read_header(path)
    lines = [
        "file       : %s" % header.path,
        "magic      : %s" % header.magic.hex(),
        "version    : Python %s" % header.version,
        "flags      : 0x%08x (%s)" % (header.flags, header.invalidation_mode),
        "payload    : byte %d" % header.payload_offset,
    ]
    if header.source_hash:
        lines.append("hash       : %s" % header.source_hash.hex())
    if header.timestamp is not None:
        lines.append("compiled   : %s" % timestamp_text(header))
    if header.source_size is not None:
        lines.append("source size: %d" % header.source_size)
    return "\n".join(lines)
