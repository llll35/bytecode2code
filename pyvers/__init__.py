"""Cross version ``.pyc`` support for CPython 3.9 - 3.14.

The rest of this repository decompiles bytecode with the running interpreter's
own ``dis``/``opcode`` tables, which by definition only ever works for the
version it was written for.  :mod:`pyvers` solves that without touching that
code: the host parses the ``.pyc`` header, looks up which bytecode family it
belongs to, and hands the file to the matching interpreter in
``embed_python/``, which runs a small worker (:mod:`pyvers.worker`) that does
the ``marshal.loads`` and the disassembly.

Typical use::

    import pyvers

    print(pyvers.header_of("module.pyc").version)   # '3.12'
    print(pyvers.decompile("module.pyc")["source"])

Python 3.9 and 3.10 share the same opcode numbering, so those versions get a
full decompilation through the project's existing ``bytecode2code.Decompiler``.
:mod:`pyvers.decomp_compat` restores the 3.9 control flow shapes that 3.10's
optimizer changed, without editing that module.  3.11 and 3.12 changed the
calling convention, the exception tables and introduced super instructions, so
:mod:`pyvers.decomp311` back-translates their instruction stream into the 3.9
shape the existing reader expects -- again without editing it.  3.13 and 3.14
still only get a normalized pseudo source skeleton plus a complete machine
readable IR.

The same operations are available from the command line::

    python main.py info
    python main.py header module.pyc
    python main.py decompile module.pyc

and the whole stack is exercised by::

    python main.py selftest
"""

from .dispatch import (call, call_pyc, code_info, compile_source, decompile,
                       disassemble, dump_ir, skeleton)
from .errors import (InterpreterNotFoundError, MarshalError, PyversError,
                     UnsupportedVersionError, WorkerError)
from .interp import (available_versions, current_version, embed_dir,
                     interpreter_path, probe_version)
from .pycfile import PYCHeader, read_header, timestamp_text
from .versions import (FULL_DECOMPILE_VERSIONS, MAGIC_VERSIONS,
                       SUPPORTED_VERSIONS, version_from_magic)

__version__ = "0.1.0"

__all__ = [
    "FULL_DECOMPILE_VERSIONS",
    "InterpreterNotFoundError",
    "MAGIC_VERSIONS",
    "MarshalError",
    "PYCHeader",
    "PyversError",
    "SUPPORTED_VERSIONS",
    "UnsupportedVersionError",
    "WorkerError",
    "available_versions",
    "call",
    "call_pyc",
    "code_info",
    "compile_source",
    "current_version",
    "decompile",
    "disassemble",
    "dump_ir",
    "embed_dir",
    "header_of",
    "interpreter_path",
    "probe_version",
    "read_header",
    "skeleton",
    "timestamp_text",
    "version_from_magic",
]


def header_of(path):
    """Convenience alias for :func:`read_header`."""
    return read_header(path)
