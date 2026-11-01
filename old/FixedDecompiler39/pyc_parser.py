import struct
import marshal
import dis
import sys
import time
from dataclasses import dataclass, field
from typing import Optional, List

from .errors import PYCError, UnsupportedBytecodeError

__all__ = [
    "PyCFile",
    "PyCParser",
    "collect_code_objects",
    "UnsupportedBytecodeError",
]


@dataclass
class PyCFile:
    magic: int
    flags: int
    timestamp: Optional[int] = None
    source_size: Optional[int] = None
    hash_value: Optional[bytes] = None
    code: object = None
    python_version: str = ""
    raw_data: bytes = field(default_factory=bytes)

    @property
    def is_hash_based(self) -> bool:
        return bool(self.flags & 0x1)

    @property
    def check_source(self) -> bool:
        return not bool(self.flags & 0x2)

    @property
    def magic_hex(self) -> str:
        return f"0x{self.magic:04x}"

    def format_header(self) -> str:
        lines = [
            f"Magic: {self.magic_hex} (Python {self.python_version})",
            f"Flags: {self.flags:#x}",
        ]
        if self.is_hash_based:
            hash_hex = self.hash_value.hex() if self.hash_value else "N/A"
            lines.append(f"Hash: {hash_hex}")
            lines.append(f"Check source: {self.check_source}")
        else:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(self.timestamp)) if self.timestamp is not None else "N/A"
            lines.append(f"Timestamp: {self.timestamp} ({ts} UTC)")
            lines.append(f"Source size: {self.source_size}")
        return "\n".join(lines)


class PyCParser:
    """Decode a ``.pyc`` header and the code object behind it.

    A ``.pyc`` header is a 4 byte magic number followed by 12 bytes (Python
    3.3 - 3.6) or 16 bytes (3.7+, PEP 552) of provenance.  Only the first two
    magic bytes carry the bytecode format; the rest identifies the
    interpreter that wrote the file.  The format bytes are what decide whether
    the running interpreter can ``marshal.loads`` the payload, so they are the
    key used throughout.
    """

    #: bytecode format -> CPython version.
    #:
    #: Read back from the interpreters in ``embed_python/`` for 3.9 and newer;
    #: the older entries are CPython's own published magic numbers.  Note that
    #: these are the *low two bytes*, i.e. ``int.from_bytes(
    #: importlib.util.MAGIC_NUMBER[:2], "little")`` -- the full four byte
    #: value read from a 3.9 file is ``0xa0d0d61``, not ``0x0d61``.
    _MAGIC_VERSIONS = {
        0x0A0D: "1.5",
        0x0B71: "1.6",
        0x0B72: "2.0",
        0x0B73: "2.1",
        0x0B74: "2.2",
        0x0B75: "2.3",
        0x0B76: "2.4",
        0x0B77: "2.5",
        0x0B78: "2.6",
        0x0B79: "2.7",
        0x0C30: "3.0",
        0x0C31: "3.1",
        0x0C32: "3.2",
        0x0C33: "3.3",
        0x0C34: "3.4",
        0x0C35: "3.5",
        0x0C36: "3.6",
        0x0D33: "3.7",
        0x0D41: "3.8",
        0x0D61: "3.9",
        0x0D6F: "3.10",
        0x0DA7: "3.11",
        0x0DCB: "3.12",
        0x0DF3: "3.13",
        0x0E2B: "3.14",
    }

    @classmethod
    def get_python_version(cls, magic: int) -> str:
        """Version behind a magic number, given either its low two bytes or
        the full four byte value read out of the file."""
        return cls._MAGIC_VERSIONS.get(
            magic & 0xFFFF, f"unknown-0x{magic & 0xFFFF:04x}"
        )

    @classmethod
    def _header_size(cls, version: str) -> int:
        return 12 if version and cls._version_key(version) < (3, 7) else 16

    @staticmethod
    def _version_key(version: str):
        major, _, minor = version.partition(".")
        try:
            return (int(major), int(minor))
        except ValueError:
            return (0, 0)

    @classmethod
    def parse(cls, data: bytes) -> PyCFile:
        if len(data) < 16:
            raise PYCError(f"File too small to be a valid .pyc file: {len(data)} bytes")

        # Read the 4-byte magic number (PEP 3147: 3.7+).  Only the low two
        # bytes identify the bytecode format.
        magic = struct.unpack_from("<I", data, 0)[0]
        python_version = cls.get_python_version(magic)

        # Python 3.3 - 3.6 stored magic + mtime + source size.  3.7+ stores
        # magic + flags and puts the mtime/size pair, or a source hash, behind
        # the flags.
        offset = 8
        flags = 0
        if cls._header_size(python_version) == 16:
            flags = struct.unpack_from("<I", data, 4)[0]
            if flags & 0x1:
                # Hash-based (PEP 552, 3.7+)
                hash_value = data[offset:offset + 8]
                offset += 8
                timestamp = None
                source_size = None
            else:
                # Timestamp-based (3.7-3.11)
                timestamp = struct.unpack_from("<I", data, offset)[0]
                offset += 4
                source_size = struct.unpack_from("<I", data, offset)[0]
                offset += 4
                hash_value = None
        else:
            timestamp = struct.unpack_from("<I", data, offset)[0]
            offset += 4
            source_size = struct.unpack_from("<I", data, offset)[0]
            offset += 4
            hash_value = None

        if offset > len(data):
            raise PYCError(
                "Truncated .pyc header: a Python %s header is %d bytes, "
                "the file has %d" % (python_version, offset, len(data))
            )

        try:
            code = marshal.loads(data[offset:])
        except (ValueError, EOFError, TypeError) as exc:
            raise UnsupportedBytecodeError(
                "cannot read a Python %s payload with Python %d.%d: marshal has no "
                "cross-version compatibility (%s). Run this with a matching "
                "interpreter, or use `python main.py decompile` which picks one."
                % (python_version, sys.version_info[0], sys.version_info[1], exc)
            ) from exc
        if not hasattr(code, "co_code"):
            raise PYCError(
                "The marshalled payload does not contain a code object (found %r)"
                % type(code).__name__
            )

        pyc_file = PyCFile(
            magic=magic,
            flags=flags,
            timestamp=timestamp,
            source_size=source_size,
            hash_value=hash_value,
            code=code,
            python_version=python_version,
            raw_data=data,
        )
        return pyc_file

    @classmethod
    def parse_file(cls, path: str) -> PyCFile:
        with open(path, "rb") as f:
            data = f.read()
        return cls.parse(data)


def collect_code_objects(code, depth=0, result=None):
    if result is None:
        result = []
    result.append((depth, code))
    for const in getattr(code, "co_consts", []) or []:
        if hasattr(const, "co_code"):
            collect_code_objects(const, depth + 1, result)
    return result
