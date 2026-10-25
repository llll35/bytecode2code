"""Unified entry point for the bytecode2code decompiler (new framework only).

No dependency on the archived `pyvers` / `bytecode2code` framework.
The self-contained version folders (`py39Decompiler` ... `Py315Decompiler`)
are the only decompilers used.
"""

import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ------------------------------------------------------------------
# selftest (new framework)
# ------------------------------------------------------------------

def _cmd_selftest(args):
    from tests import selftest
    # pass args through; selftest reads sys.argv
    sys.argv = [sys.argv[0]] + args
    return selftest.main()


def _cmd_demo(args):
    import tempfile
    sample = '\n'.join([
        'def add(a, b):',
        '    return a + b',
        '',
        'def classify(n):',
        '    if n > 100:',
        '        return "large"',
        '    elif n > 50:',
        '        return "medium"',
        '    return "small"',
    ])
    versions = ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14", "3.15")
    print("=" * 64)
    print("BYTECODE2CODE CROSS VERSION DEMO (new framework)")
    print("=" * 64)
    results = []
    with tempfile.TemporaryDirectory(prefix="b2c_demo_") as folder:
        for version in versions:
            py = os.path.join(_ROOT, "embed_python", "python-" + version, "python.exe")
            if not os.path.isfile(py):
                print("  %s interpreter missing, skipped" % version)
                continue
            target = os.path.join(folder, version + ".pyc")
            # compile with embedded interpreter
            src_path = os.path.join(folder, version + ".py")
            with open(src_path, "w", encoding="utf-8") as f:
                f.write(sample)
            subprocess.run(
                [py, "-c",
                 "import py_compile,sys; "
                 "py_compile.compile(sys.argv[1], cfile=sys.argv[2], doraise=True)",
                 src_path, target],
                check=True,
            )
            # Parse and decompile in the matching interpreter: marshal data
            # cannot be read by a different Python version.
            script = (
                "import importlib,sys; "
                "root,path=sys.argv[1:]; sys.path.insert(0,root); "
                "v='%d.%d' % sys.version_info[:2]; "
                "p='Py315Decompiler' if v=='3.15' else "
                "'py%sDecompiler' % v.replace('.',''); "
                "parser=importlib.import_module(p+'.pyc_parser'); "
                "code=parser.PyCParser.parse_file(path).code; "
                "print(importlib.import_module(p).decompile(code))"
            )
            completed = subprocess.run(
                [py, "-I", "-c", script, _ROOT, target],
                capture_output=True, text=True, encoding="utf-8",
                check=True,
            )
            rebuilt = completed.stdout
            print("  %s -> %d chars" % (version, len(rebuilt)))
            results.append((version, rebuilt))
    print()
    if results:
        version, rebuilt = results[-1]
        print("last sample (%s) source:" % version)
        print("-" * 64)
        print(rebuilt)
    return 0


# ------------------------------------------------------------------
# minimal CLI dispatcher
# ------------------------------------------------------------------

def _cmd_decompile(args):
    import importlib
    from tests.equivalence import version_of
    target = args[0] if args else None
    if not target or not os.path.isfile(target):
        print("usage: decompile <file.pyc>")
        return 2
    parsed = importlib.import_module("py39Decompiler.pyc_parser").PyCParser.parse_file(target)
    folder = "py%sDecompiler" % parsed.python_version.replace(".", "")
    if not os.path.isdir(folder):
        print("no decompiler folder for %s" % parsed.python_version)
        return 1
    mod = importlib.import_module(folder)
    print(mod.decompile(parsed.code))
    return 0


def _cmd_dis(args):
    import dis, importlib
    target = args[0] if args else None
    if not target or not os.path.isfile(target):
        print("usage: dis <file.pyc>")
        return 2
    from tests.equivalence import version_of
    version = version_of(target) or "3.9"
    parser_folder = "py%sDecompiler.pyc_parser" % version.replace(".", "")
    parsed = importlib.import_module(parser_folder).PyCParser.parse_file(target)
    dis.dis(parsed.code)
    return 0


def _cmd_compile(args):
    import py_compile, tempfile, os
    source_path = args[0] if args else None
    ver = "3.9"
    if "--version" in args:
        idx = args.index("--version")
        if idx + 1 < len(args):
            ver = args[idx + 1]
    if not source_path or not os.path.isfile(source_path):
        print("usage: compile <file.py> [--version X.Y]")
        return 2
    out_path = source_path.replace(".py", ".pyc")
    interpreter = os.path.join(_ROOT, "embed_python", "python-" + ver, "python.exe")
    if not os.path.isfile(interpreter):
        print("interpreter for %s not found" % ver)
        return 1
    subprocess.run([interpreter, "-c", "import py_compile,sys; py_compile.compile(sys.argv[1], cfile=sys.argv[2], doraise=True)", source_path, out_path], check=True)
    print("compiled %s -> %s (python %s)" % (source_path, out_path, ver))
    return 0


def _cmd_info(args):
    versions = ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14", "3.15")
    for v in versions:
        folder = ("Py315Decompiler" if v == "3.15" else "py%sDecompiler" % v.replace(".", ""))
        exists = os.path.isdir(folder)
        interp_path = os.path.join(_ROOT, "embed_python", "python-" + v, "python.exe")
        interp_exists = os.path.isfile(interp_path)
        print("%-6s folder=%-3s interpreter=%-3s" % (v, "yes" if exists else "no", "yes" if interp_exists else "no"))
    return 0


def _cmd_versions(args):
    _cmd_info([])
    return 0


def _cmd_skeleton(args):
    return _cmd_decompile(args)


def _cmd_ir(args):
    import importlib
    target = args[0] if args else None
    if not target or not os.path.isfile(target):
        print("usage: ir <file.pyc>")
        return 2
    from tests.equivalence import version_of
    version = version_of(target)
    parser_folder = "py%sDecompiler.pyc_parser" % version.replace(".", "") if version else "py39Decompiler.pyc_parser"
    parsed = importlib.import_module(parser_folder).PyCParser.parse_file(target)
    folder = "py%sDecompiler" % parsed.python_version.replace(".", "")
    if not os.path.isdir(folder):
        print("no decompiler folder for %s" % parsed.python_version)
        return 1
    mod = importlib.import_module(folder)
    import json
    instrs = mod.decompile(parsed.code)
    print(instrs)
    return 0


def _cmd_header(args):
    import importlib
    target = args[0] if args else None
    if not target or not os.path.isfile(target):
        print("usage: header <file.pyc>")
        return 2
    from tests.equivalence import version_of
    version = version_of(target) or "3.9"
    parser_folder = "py%sDecompiler.pyc_parser" % version.replace(".", "")
    parsed = importlib.import_module(parser_folder).PyCParser.parse_file(target)
    print("version:", parsed.python_version)
    print("magic:", hex(parsed.magic))
    print("timestamp:", parsed.timestamp)
    return 0


def _cmd_code_info(args):
    return _cmd_ir(args)


# ------------------------------------------------------------------
# dispatcher mapping
# ------------------------------------------------------------------

ALIASES = {
    "d": "decompile",
    "dis": "dis",
    "disassemble": "dis",
    "i": "info",
    "infos": "code-info",
}

COMMANDS = {
    "selftest": _cmd_selftest,
    "demo": _cmd_demo,
    "versions": _cmd_versions,
    "decompile": _cmd_decompile,
    "dis": _cmd_dis,
    "disassemble": _cmd_dis,
    "compile": _cmd_compile,
    "skeleton": _cmd_skeleton,
    "ir": _cmd_ir,
    "code-info": _cmd_code_info,
    "infos": _cmd_code_info,
    "header": _cmd_header,
    "info": _cmd_info,
    "i": _cmd_info,
}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python main.py <command> [options]")
        print("  decompile <file.pyc>    source (alias: d)")
        print("  dis <file.pyc>          disassembly (aliases: dis, disassemble)")
        print("  compile <file.py> [--version X.Y]")
        print("  skeleton <file.pyc>     pseudo source")
        print("  ir <file.pyc>           instruction JSON")
        print("  code-info <file.pyc>    code hierarchy (alias: infos)")
        print("  header <file.pyc>       .pyc header")
        print("  info [<file.pyc>]       versions (alias: i)")
        print("  versions                supported versions")
        print("  selftest                regression suite")
        print("  demo                    round-trip demo")
        return 2
    cmd = args[0]
    rest = args[1:]
    if cmd in ALIASES:
        cmd = ALIASES[cmd]
    if cmd not in COMMANDS:
        print("unknown command:", cmd)
        return 2
    return COMMANDS[cmd](rest)


if __name__ == "__main__":
    sys.exit(main())
