"""Worker executed *inside the target interpreter*.

The host process starts it as ``python.exe pyvers/worker.py request.json``.  The
script is self bootstrapping because the embedded interpreters only put their own
zip and directory on ``sys.path``.

It is the only place where ``marshal.loads`` happens, because that call is
hard bound to the running interpreter.

Everything is imported through the :mod:`pyvers` package rather than as a bare
top level module, so the worker shares one module identity with the host
process instead of loading a second, private copy of every module.
"""

import json
import marshal
import os
import sys

sys.dont_write_bytecode = True  # never leave .pyc litter in the repository

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pyvers.protocol import encode  # noqa: E402
from pyvers import normalize  # noqa: E402
from pyvers.versions import FULL_DECOMPILE_VERSIONS  # noqa: E402


def host_version():
    return "%d.%d" % sys.version_info[:2]


def load_code(pyc_path, payload_offset):
    """Unmarshal the payload of a .pyc written by *this* interpreter."""
    with open(pyc_path, "rb") as handle:
        blob = handle.read()
    if payload_offset is None or payload_offset > len(blob):
        raise ValueError("bad payload offset %r for %s" % (payload_offset,
                                                           pyc_path))
    return marshal.loads(blob[payload_offset:])


def code_tree(code, depth=0, limit=4):
    """Compact recursive summary of the code object hierarchy."""
    node = {
        "name": code.co_name,
        "qualname": getattr(code, "co_qualname", code.co_name),
        "kind": normalize.code_kind(code),
        "signature": normalize.signature(code, code.co_name == "<module>"),
        "tags": normalize.function_flags(code),
        "firstlineno": code.co_firstlineno,
        "argcount": code.co_argcount,
        "flags": code.co_flags,
        "stacksize": code.co_stacksize,
        "nlocals": getattr(code, "co_nlocals", len(code.co_varnames)),
    }
    if depth < limit:
        children = [code_tree(c, depth + 1, limit) for c in
                    normalize.nested_codes(code)]
        if children:
            node["children"] = children
    return node


def decompile_with_existing(code):
    """Reuse the project's 3.9 decompiler, plus the 3.10 compatibility shim."""
    from pyvers import decomp_compat
    return decomp_compat.make_decompiler(host_version()).decompile(code)


def _repo_root():
    return _REPO_ROOT


def compile_source(source, out_path, dfile="<pyvers>", optimize=0,
                   hash_mode=False):
    """Compile *source* with this interpreter and write a .pyc next to it."""
    import py_compile
    import tempfile

    out_path = os.path.abspath(out_path)
    folder = os.path.dirname(out_path) or "."
    if not os.path.isdir(folder):
        os.makedirs(folder)
    handle, temp_path = tempfile.mkstemp(suffix=".py", dir=folder)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(source)
        extra = {}
        if hash_mode:
            extra["invalidation_mode"] = py_compile.PycInvalidationMode.CHECKED_HASH
        py_compile.compile(temp_path, cfile=out_path, dfile=dfile,
                           doraise=True, optimize=optimize, **extra)
    finally:
        try:
            os.unlink(temp_path)
        except OSError:  # pragma: no cover - best effort cleanup
            pass
    return out_path


# --------------------------------------------------------------------------
# operations
# --------------------------------------------------------------------------

def op_info(request):
    return {
        "interpreter": host_version(),
        "implementation": sys.implementation.name,
        "full_decompile": host_version() in FULL_DECOMPILE_VERSIONS,
    }


def op_code_info(request):
    code = load_code(request["pyc"], request.get("payload_offset"))
    return {
        "code": code_tree(code),
        "header": request.get("header"),
    }


def op_disassemble(request):
    code = load_code(request["pyc"], request.get("payload_offset"))
    return {
        "text": normalize.render_disassembly(code),
        "ir": normalize.build_ir(code, code.co_name == "<module>"),
    }


def op_dump_ir(request):
    code = load_code(request["pyc"], request.get("payload_offset"))
    return {"ir": normalize.build_ir(code, code.co_name == "<module>")}


def op_skeleton(request):
    code = load_code(request["pyc"], request.get("payload_offset"))
    return {"text": normalize.render_skeleton(code, host_version())}


def op_decompile(request):
    version = host_version()
    code = load_code(request["pyc"], request.get("payload_offset"))
    if version in FULL_DECOMPILE_VERSIONS:
        return {
            "source": decompile_with_existing(code),
            "mode": "full",
            "version": version,
        }
    return {
        "source": normalize.render_skeleton(code, version),
        "mode": "skeleton",
        "version": version,
    }


def op_compile(request):
    out = compile_source(request["source"], request["out"],
                         request.get("dfile", "<pyvers>"),
                         request.get("optimize", 0),
                         request.get("hash_mode", False))
    return {"out": out, "version": host_version()}


OPERATIONS = {
    "info": op_info,
    "code_info": op_code_info,
    "disassemble": op_disassemble,
    "dump_ir": op_dump_ir,
    "skeleton": op_skeleton,
    "decompile": op_decompile,
    "compile": op_compile,
}


def handle(request):
    """Run one request and return the response payload."""
    operation = OPERATIONS.get(request.get("op"))
    if operation is None:
        raise ValueError("unknown operation %r" % request.get("op"))
    return operation(request)


def main(argv):
    try:
        with open(argv[1], "r", encoding="utf-8") as stream:
            request = json.load(stream)
        payload = {"ok": True, "version": host_version(),
                   "data": handle(request)}
    except BaseException as exc:  # noqa: BLE001 - report everything verbatim
        import traceback
        payload = {
            "ok": False,
            "version": host_version(),
            "error": "%s: %s" % (type(exc).__name__, exc),
            "traceback": traceback.format_exc(),
        }
    # The host always reads the response back as UTF-8, so the bytes have to
    # be written as UTF-8 too.  ``sys.stdout`` is bound to the console code
    # page instead -- on a Chinese Windows that is GBK -- and encoding the
    # payload through it turns every non-ASCII character of the decompiled
    # source into U+FFFD on the way out.
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:  # a worker run with stdout replaced by a text stream
        sys.stdout.write(encode(payload))
        sys.stdout.flush()
    else:
        stream.write(encode(payload).encode("utf-8"))
        stream.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
