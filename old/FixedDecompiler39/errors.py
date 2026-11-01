"""Errors raised by :mod:`bytecode2code`.

Every failure the library reports on purpose comes from this hierarchy, so a
caller can tell "this file is not something I can read" apart from "this file is
malformed" apart from a bug in the decompiler.  The CLI turns each of them into
a one-line message and an exit status; anything else is a bug and keeps its
traceback.

The classes live here rather than next to the code that raises them so that
importing any one of them cannot pull in the module doing the importing.
"""


class Bytecode2CodeError(Exception):
    """Base class for every error this package raises deliberately."""


class PYCError(Bytecode2CodeError):
    """A ``.pyc`` file could not be read.

    The file exists and starts with a plausible header, so the problem is in
    the header or the marshalled payload behind it.
    """


class UnsupportedBytecodeError(PYCError):
    """The file is a valid ``.pyc``, but not one this interpreter can read.

    ``marshal`` has no cross-version compatibility, so a ``.pyc`` written by a
    different CPython has to be handed to an interpreter that matches it.
    """


class DecompilationError(Bytecode2CodeError):
    """A code object could not be turned back into source.

    Recovering source from bytecode is a best-effort reconstruction, so this
    names the *result* being unavailable rather than a specific malformed
    opcode.
    """


__all__ = [
    "Bytecode2CodeError",
    "PYCError",
    "UnsupportedBytecodeError",
    "DecompilationError",
]