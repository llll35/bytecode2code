"""Discovery of the embedded CPython interpreters shipped in ``embed_python``.

A ``.pyc`` payload can only be decoded by the interpreter that produced it, so
every request is routed to the matching ``python.exe``.  The interpreters are
located in ``embed_python/python-X.Y/`` relative to the repository root; set
``PYVERS_EMBED_DIR`` to override that location.
"""

import os
import subprocess
import sys

from .errors import InterpreterNotFoundError
from .versions import SUPPORTED_VERSIONS, magic_key, version_key

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(PACKAGE_DIR)
WORKER_SCRIPT = os.path.join(PACKAGE_DIR, "worker.py")

_EXE_NAMES = ("python.exe", "python3.exe", "python3", "python")

_magic_cache = {}


def current_version():
    """The bytecode version of the interpreter running this process."""
    return "%d.%d" % sys.version_info[:2]


def current_magic():
    import importlib.util
    return importlib.util.MAGIC_NUMBER


def embed_dir():
    """Directory that holds the ``python-X.Y`` interpreter folders."""
    override = os.environ.get("PYVERS_EMBED_DIR")
    if override:
        return override
    return os.path.join(REPO_ROOT, "embed_python")


def interpreter_path(version):
    """Absolute path of the interpreter for *version*, or ``None``."""
    candidates = []
    folder = os.path.join(embed_dir(), "python-%s" % version)
    for name in _EXE_NAMES:
        candidates.append(os.path.join(folder, name))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def available_versions():
    """Sorted list of versions that have a usable interpreter on disk."""
    found = []
    for version in SUPPORTED_VERSIONS:
        if interpreter_path(version) is not None:
            found.append(version)
    found.sort(key=version_key)
    return found


def interpreter_magic(version):
    """Ask the interpreter for its own magic number.  Cached, may be ``None``."""
    if version in _magic_cache:
        return _magic_cache[version]
    path = interpreter_path(version)
    magic = None
    if path is not None:
        try:
            proc = subprocess.run(
                [path, "-I", "-c",
                 "import importlib.util as u, sys;"
                 "sys.stdout.buffer.write(u.MAGIC_NUMBER)"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            proc = None
        if proc is not None and proc.returncode == 0 and proc.stdout:
            magic = proc.stdout[:4]
    _magic_cache[version] = magic
    return magic


def probe_version(magic):
    """Find the installed interpreter that can decode *magic*.

    Used when the static magic table does not know the number, e.g. for
    pre-release builds.  Returns a version string or ``None``.
    """
    wanted = magic_key(magic)
    for version in available_versions():
        if magic_key(interpreter_magic(version)) == wanted:
            return version
    return None


def require_interpreter(version, magic=None):
    """Return the interpreter for *version*, raising a helpful error if absent."""
    path = interpreter_path(version)
    if path is None:
        raise InterpreterNotFoundError(
            "no interpreter for Python %s under %s; expected %s"
            % (version, embed_dir(), os.path.join("python-%s" % version,
                                                  _EXE_NAMES[0]))
        )
    if magic is not None and magic_key(interpreter_magic(version)) != \
            magic_key(magic):
        raise InterpreterNotFoundError(
            "Python %s at %s does not accept bytecode %s (it wants %s)"
            % (version, path, magic_key(magic).hex(),
               magic_key(interpreter_magic(version)).hex())
        )
    return path
