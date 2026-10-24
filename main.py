"""Unified entry point for the bytecode2code decompiler.

The repository grew two front ends.  ``bytecode2code`` reads bytecode with the
running interpreter and therefore only ever handled the version it was written
for; :mod:`pyvers` instead routes a ``.pyc`` to whichever of the interpreters
in ``embed_python/`` can decode it.  This script is the single place both are
reachable from, so ``python main.py <command>`` is all that is needed::

    python main.py decompile module.pyc          # 3.9 - 3.14
    python main.py compile source.py --version 3.12
    python main.py info                           # which interpreters exist
    python main.py selftest                       # regression suite

The commands of ``python -m bytecode2code`` (``d``, ``dis``, ``i``, ``demo``)
and of ``python -m pyvers`` are both accepted; where they collide the pyvers
spelling wins, because it is the one that works for every version.  Every
``.pyc`` command auto-detects the bytecode version from the file header.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pyvers import __main__ as _cli  # noqa: E402
from pyvers import compile_source, decompile, interp  # noqa: E402
from pyvers import selftest as _selftest  # noqa: E402
from pyvers.errors import PyversError  # noqa: E402
from pyvers.pycfile import describe  # noqa: E402

PROG = "python main.py"


# --------------------------------------------------------------------------
# commands that only exist here
# --------------------------------------------------------------------------

def _cmd_versions(_args):
    """Show the magic number table and where each interpreter lives."""
    from pyvers.versions import (FULL_DECOMPILE_VERSIONS, MAGIC_VERSIONS,
                                 SUPPORTED_VERSIONS)

    print("embed dir: %s" % interp.embed_dir())
    print("host     : %s" % interp.current_version())
    print()
    print("%-8s %-8s %-9s %s"
          % ("magic", "version", "decompile", "interpreter"))
    for version in SUPPORTED_VERSIONS:
        magic = next((m for m, v in MAGIC_VERSIONS.items() if v == version), b"")
        path = interp.interpreter_path(version)
        mode = "full" if version in FULL_DECOMPILE_VERSIONS else "skeleton"
        print("%-8s %-8s %-9s %s"
              % (magic.hex() or "?", version, mode, path or "MISSING"))
    return 0


def _cmd_selftest(_args):
    """Run the cross version regression suite."""
    return _selftest.main()


def _cmd_demo(_args):
    """Compile a sample with every interpreter and read each one back.

    This is the whole point of the cross version layer in one command: the
    ``.pyc`` is produced by whichever interpreter is asked for and decoded by
    whichever one owns that bytecode.
    """
    import tempfile

    sample = '\n'.join([
        '"""Module docstring for demo."""',
        "",
        "CONSTANT = 42",
        "",
        "",
        "def add(a, b):",
        '    """Add two numbers."""',
        "    return a + b",
        "",
        "",
        "def classify(n):",
        '    """Return a label for *n*."""',
        "    if n > 100:",
        '        return "large"',
        "    elif n > 50:",
        '        return "medium"',
        '    return "small"',
        "",
        "",
        "class Counter:",
        '    """A simple counter."""',
        "",
        "    def __init__(self, start=0):",
        "        self.value = start",
        "        self.seen = [i for i in range(start)]",
        "",
        "    def increment(self, step=1):",
        "        self.value += step",
        "        return self.value",
        "",
        "",
        "def main():",
        "    counter = Counter()",
        "    counter.increment(5)",
        "    squares = {i: i * i for i in range(4)}",
        '    print("Counter:", counter.value)',
        '    print("squares:", squares)',
        "",
    ])

    print("=" * 64)
    print("BYTECODE2CODE CROSS VERSION DEMO")
    print("=" * 64)
    versions = interp.available_versions()
    print("available interpreters: %s\n" % ", ".join(versions))

    results = []
    with tempfile.TemporaryDirectory(prefix="b2c_demo_") as folder:
        for version in versions:
            pyc = os.path.join(folder, "%s.pyc" % version)
            compile_source(sample, pyc, version=version, dfile="<demo>")
            data = decompile(pyc)
            results.append((version, data))
            print("  compiled with %-5s -> decompiled %-5s %s"
                  % (version, data.get("version"), data.get("mode")))

    if not results:
        print("no interpreter available; nothing to demonstrate")
        return 1

    full = [entry for entry in results if entry[1].get("mode") == "full"]
    version, data = full[-1] if full else results[-1]
    print()
    print("source decompiled from %s bytecode:" % version)
    print("-" * 64)
    print(data["source"])
    return 0


#: The commands the original ``bytecode2code`` CLI used, mapped onto the
#: pyvers spelling so both front ends can be typed interchangeably.
_ALIASES = {
    "d": "decompile",
    "dis": "dis",
    "disassemble": "dis",
    "i": "info",
    "infos": "code-info",
}

#: Commands implemented above rather than in :mod:`pyvers.__main__`.
_EXTRA = {
    "versions": _cmd_versions,
    "selftest": _cmd_selftest,
    "demo": _cmd_demo,
}

_USAGE = """\
usage: python main.py <command> [options]

reading a .pyc (the version is detected from the file):
  decompile <file.pyc>      decompile to source          [alias: d]
  dis <file.pyc>            native disassembly  [aliases: disassemble, dis]
  skeleton <file.pyc>       normalized pseudo source
  ir <file.pyc>             normalized instruction tree (JSON)
  code-info <file.pyc>      code object hierarchy (JSON)  [alias: infos]
  header <file.pyc>         decoded .pyc header
  info [<file.pyc>]         interpreters, or one file's details  [alias: i]

producing a .pyc:
  compile <file.py>         compile with a chosen interpreter

the project itself:
  versions                  magic number table and decompile coverage
  selftest                  run the regression suite
  demo                      cross version round trip

Run 'python main.py <command> --help' for the options of one command.
"""


def _info(args):
    """Interpreters, plus the details of one file when a path is given.

    The original CLI's ``info`` took a ``.pyc`` while pyvers' takes none, so
    both spellings are honoured: with a path it describes that file, without
    one it lists the interpreters.
    """
    if not args:
        return _cli.main(["info"], PROG)
    print(describe(args[0]))
    from pyvers import dispatch

    tree = dispatch.code_info(args[0])
    print()
    print("code objects:")
    _print_code_tree(tree, "  ")
    return 0


def _print_code_tree(node, indent):
    label = node.get("signature") or node.get("name")
    print("%s%s  [%s] line %s"
          % (indent, label, node.get("kind"), node.get("firstlineno")))
    for child in node.get("children") or ():
        _print_code_tree(child, indent + "  ")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in _ALIASES:
        argv[0] = _ALIASES[argv[0]]
    if argv and argv[0] in _EXTRA:
        return _guard(_EXTRA[argv[0]], argv[1:])
    if argv and argv[0] == "info":
        return _guard(_info, argv[1:])
    if not argv:
        sys.stdout.write(_USAGE)
        return 2
    if argv[0] in ("-h", "--help", "help"):
        sys.stdout.write(_USAGE)
        return 0
    return _guard(_cli.main, argv, PROG)


def _guard(handler, args, prog=None):
    """Run *handler*, turning the package's errors into a message + status."""
    try:
        if prog is None:
            return handler(args)
        return handler(args, prog)
    except PyversError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1
    except FileNotFoundError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())