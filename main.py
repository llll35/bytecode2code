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

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python main.py <command>")
        print("  selftest              full-version regression suite")
        print("  demo                  cross-version round-trip demo")
        print("  versions              supported versions")
        return 2
    cmd = args[0]
    rest = args[1:]
    if cmd == "selftest":
        return _cmd_selftest(rest)
    if cmd == "demo":
        return _cmd_demo(rest)
    if cmd == "versions":
        print("supported versions:")
        versions = ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14", "3.15")
        for v in versions:
            folder = ("Py315Decompiler" if v == "3.15"
                      else "py%sDecompiler" % v.replace(".", ""))
            exists = os.path.isdir(folder)
            print("  %-6s %s" % (v, "present" if exists else "MISSING"))
        return 0
    if cmd in ("decompile", "d"):
        # simple wrapper: detect version from .pyc and decompile
        import importlib
        from tests.equivalence import version_of
        target = rest[0] if rest else None
        if not target:
            print("usage: decompile <file.pyc>")
            return 2
        with open(target, "rb") as handle:
            magic = int.from_bytes(handle.read(2), "little")
        if magic == 0x0E52:
            interpreter = os.path.join(
                _ROOT, "embed_python", "python-3.15", "python.exe")
            if not os.path.isfile(interpreter):
                sys.stderr.write(
                    "Python 3.15 bytecode requires embed_python/python-3.15/python.exe\n"
                )
                return 1
            worker = os.path.join(_ROOT, "Py315Decompiler", "worker.py")
            completed = subprocess.run(
                [interpreter, "-I", worker, os.path.abspath(target)],
                capture_output=True, text=True, encoding="utf-8",
                cwd=_ROOT,
            )
            if completed.returncode:
                sys.stderr.write(completed.stderr)
                return completed.returncode
            sys.stdout.write(completed.stdout)
            return 0
        parsed = importlib.import_module("py39Decompiler.pyc_parser").PyCParser.parse_file(target)
        version = parsed.python_version
        folder = "py%sDecompiler" % version.replace(".", "")
        if not os.path.isdir(folder):
            print("no decompiler folder for %s" % version)
            return 1
        mod = importlib.import_module(folder)
        source = mod.decompile(parsed.code)
        print(source)
        return 0
    print("unknown command:", cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
