"""Command line front end: ``python -m pyvers <command> <file.pyc>``.

Commands
--------
``info``       interpreters found and their bytecode families
``header``     decoded ``.pyc`` header
``code-info``  recursive code object summary
``dis``        native disassembly of every nested code object
``ir``         normalized, JSON serialisable instruction tree
``skeleton``   normalized pseudo source listing
``decompile``  decompiled source (full up to 3.12, skeleton above that)
``compile``    compile a ``.py`` with one of the available interpreters
"""

import argparse
import json
import os
import sys

from . import __version__, dispatch, interp
from .errors import PyversError
from .pycfile import describe, read_header
from .versions import SUPPORTED_VERSIONS


def _emit(text, out_path, as_json):
    if as_json:
        text = json.dumps(text, ensure_ascii=False, indent=2, default=str)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as stream:
            stream.write(text + "\n")
    else:
        sys.stdout.write(text + "\n")


def _cmd_info(args):
    rows = []
    for version in SUPPORTED_VERSIONS:
        try:
            path = interp.interpreter_path(version)
            magic = interp.interpreter_magic(version)
            rows.append({"version": version, "path": path,
                         "magic": magic.hex()})
        except PyversError as exc:
            rows.append({"version": version, "error": str(exc)})
    if args.json:
        _emit({"embed_dir": interp.embed_dir(), "interpreters": rows},
              args.out, True)
        return 0
    print("embed dir : %s" % interp.embed_dir())
    print("host      : %s" % interp.current_version())
    print("available : %s" % ", ".join(interp.available_versions()))
    print()
    for row in rows:
        if "error" in row:
            print("%-5s  unavailable  (%s)" % (row["version"], row["error"]))
        else:
            print("%-5s  %s  magic=%s"
                  % (row["version"], row["path"], row["magic"]))
    return 0


def _cmd_header(args):
    if args.json:
        _emit(read_header(args.path).as_dict(), args.out, True)
    else:
        _emit(describe(args.path), args.out, False)
    return 0


def _cmd_code_info(args):
    _emit(dispatch.code_info(args.path, version=args.version), args.out, True)
    return 0


def _cmd_dis(args):
    data = dispatch.disassemble(args.path, version=args.version)
    if args.json:
        _emit(data["ir"], args.out, True)
    else:
        _emit(data["text"], args.out, False)
    return 0


def _cmd_ir(args):
    _emit(dispatch.dump_ir(args.path, version=args.version), args.out, True)
    return 0


def _cmd_skeleton(args):
    _emit(dispatch.skeleton(args.path, version=args.version), args.out, False)
    return 0


def _cmd_decompile(args):
    data = dispatch.decompile(args.path, version=args.version)
    if not args.quiet:
        sys.stderr.write("mode=%s version=%s\n"
                         % (data.get("mode"), data.get("version")))
    _emit(data["source"], args.out, False)
    return 0


def _cmd_compile(args):
    out = args.out or os.path.splitext(args.path)[0] + ".pyc"
    result = dispatch.compile_source(
        _read(args.path), out, version=args.version, dfile=args.dfile,
        hash_mode=args.hash_based,
    )
    _emit(result["out"], None, False)
    return 0


def _read(path):
    with open(path, "r", encoding="utf-8") as stream:
        return stream.read()


def build_parser(prog="python -m pyvers"):
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Read, disassemble and decompile CPython 3.9-3.14 .pyc files.",
    )
    parser.add_argument("--version", action="version",
                        version="pyvers %s" % __version__)
    subs = parser.add_subparsers(dest="command")

    def add(name, handler, needs_file=True, needs_version=True, help_text=""):
        sub = subs.add_parser(name, help=help_text)
        sub.set_defaults(handler=handler)
        if needs_file:
            sub.add_argument("path", help="path to the .pyc (or .py) file")
        if needs_version:
            sub.add_argument("--version", dest="version", default=None,
                             choices=SUPPORTED_VERSIONS,
                             help="override the detected bytecode version")
        sub.add_argument("-o", "--out", default=None,
                         help="write to this file instead of stdout")
        sub.add_argument("--json", action="store_true",
                         help="emit JSON instead of text")
        return sub

    add("info", _cmd_info, needs_file=False, needs_version=False,
        help_text="list interpreters")
    add("header", _cmd_header, needs_version=False,
        help_text="decode the .pyc header")
    add("code-info", _cmd_code_info, help_text="code object hierarchy (JSON)")
    add("dis", _cmd_dis, help_text="native disassembly")
    add("ir", _cmd_ir, help_text="normalized instruction tree (JSON)")
    add("skeleton", _cmd_skeleton, help_text="normalized pseudo source")
    add("decompile", _cmd_decompile, help_text="decompile to source")
    subs.choices["decompile"].add_argument(
        "-q", "--quiet", action="store_true", help="suppress the stderr banner")

    compile_sub = subs.add_parser("compile", help="compile a .py with a target")
    compile_sub.add_argument("path", help="path to the .py source")
    compile_sub.add_argument("--version", dest="version", default=None,
                             choices=SUPPORTED_VERSIONS,
                             help="interpreter version to compile with")
    compile_sub.add_argument("-o", "--out", default=None, help="output .pyc path")
    compile_sub.add_argument("--dfile", default="<pyvers>",
                             help="filename recorded in the code object")
    compile_sub.add_argument("--hash-based", action="store_true",
                             help="use checked-hash invalidation")
    compile_sub.set_defaults(handler=_cmd_compile)

    return parser


def main(argv=None, prog="python -m pyvers"):
    parser = build_parser(prog)
    args = parser.parse_args(argv)
    if getattr(args, "handler", None) is None:
        parser.print_help()
        return 2
    try:
        return args.handler(args)
    except PyversError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1
    except FileNotFoundError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
