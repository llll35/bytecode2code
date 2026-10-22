"""Host side scheduler: run one operation inside the matching interpreter.

The host never imports ``marshal``, ``dis`` or ``opcode`` for foreign bytecode.
It only decides *which* interpreter has to run the request and then relays the
JSON answer back to the caller.
"""

import json
import os
import subprocess
import tempfile

from . import interp
from .errors import MarshalError, WorkerError
from .protocol import extract, request
from .pycfile import read_header
from .versions import require_version

DEFAULT_TIMEOUT = 120


def call(version, op, magic=None, timeout=DEFAULT_TIMEOUT, **fields):
    """Run *op* in the interpreter for *version* and return the ``data`` block."""
    payload = request(op, **fields)
    response = _run(version, payload, magic=magic, timeout=timeout)
    if not response.get("ok"):
        raise WorkerError(
            "Python %s worker failed: %s"
            % (version, response.get("error", "unknown error")),
            traceback_text=response.get("traceback", ""),
        )
    return response.get("data") or {}


def _run(version, payload, magic=None, timeout=DEFAULT_TIMEOUT):
    exe = interp.require_interpreter(version, magic)
    handle, request_path = tempfile.mkstemp(prefix="pyvers_", suffix=".json")
    os.close(handle)
    try:
        with open(request_path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
        try:
            proc = subprocess.run(
                [exe, "-I", interp.WORKER_SCRIPT, request_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout, cwd=interp.REPO_ROOT,
            )
        except subprocess.TimeoutExpired:
            raise WorkerError(
                "Python %s worker timed out after %ss" % (version, timeout)
            )
    finally:
        try:
            os.unlink(request_path)
        except OSError:  # pragma: no cover - best effort cleanup
            pass

    stdout = _decode(proc.stdout)
    try:
        return extract(stdout)
    except ValueError as exc:
        raise WorkerError(
            "%s (exit code %s)\n%s\n%s"
            % (exc, proc.returncode, stdout[-2000:], _decode(proc.stderr)[-2000:])
        )


def _decode(blob):
    """Decode a captured stream.

    The worker writes UTF-8 whatever the console code page is, so decoding is
    strict: a failure here means the response was truncated or garbled, and
    substituting U+FFFD would quietly hand the caller a source file whose
    string literals no longer match the ones in the ``.pyc``.
    """
    if blob is None:
        return ""
    if isinstance(blob, bytes):
        return blob.decode("utf-8")
    return blob


# --------------------------------------------------------------------------
# .pyc oriented helpers
# --------------------------------------------------------------------------

def call_pyc(path, op, version=None, timeout=DEFAULT_TIMEOUT, **fields):
    """Run *op* against the ``.pyc`` at *path*, auto-selecting the version."""
    header = read_header(path)
    detected = require_version(header.magic)
    if version is None:
        version = detected
    elif version != detected:
        raise MarshalError(
            "%s is Python %s bytecode but Python %s was requested"
            % (path, detected, version)
        )
    fields.setdefault("pyc", os.path.abspath(path))
    fields.setdefault("payload_offset", header.payload_offset)
    return call(
        version, op, magic=header.magic, timeout=timeout, **fields
    )


def decompile(path, version=None, timeout=DEFAULT_TIMEOUT):
    """Decompile *path*; returns ``{"source", "mode", "version"}``."""
    return call_pyc(path, "decompile", version=version, timeout=timeout)


def disassemble(path, version=None, timeout=DEFAULT_TIMEOUT):
    """Return the native disassembly plus the normalized IR of *path*."""
    return call_pyc(path, "disassemble", version=version, timeout=timeout)


def skeleton(path, version=None, timeout=DEFAULT_TIMEOUT):
    """Return the normalized pseudo source listing of *path*."""
    data = call_pyc(path, "skeleton", version=version, timeout=timeout)
    return data["text"]


def dump_ir(path, version=None, timeout=DEFAULT_TIMEOUT):
    """Return the recursive, JSON friendly IR of *path*."""
    data = call_pyc(path, "dump_ir", version=version, timeout=timeout)
    return data["ir"]


def code_info(path, version=None, timeout=DEFAULT_TIMEOUT):
    """Return the code object hierarchy of *path*."""
    header = read_header(path)
    data = call_pyc(path, "code_info", version=version, timeout=timeout,
                    header=header.as_dict())
    return data["code"]


def compile_source(source, out_path, version=None, timeout=DEFAULT_TIMEOUT,
                   dfile="<pyvers>", optimize=0, hash_mode=False):
    """Compile *source* with *version* and return the produced ``.pyc`` path."""
    if version is None:
        version = interp.current_version()
    return call(version, "compile", timeout=timeout, source=source,
                out=os.path.abspath(out_path), dfile=dfile, optimize=optimize,
                hash_mode=hash_mode)
