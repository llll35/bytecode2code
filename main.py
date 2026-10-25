"""Unified entry point for the bytecode2code decompiler (new framework only).

No dependency on the archived `pyvers` / `bytecode2code` framework.
The self-contained version folders (`py39Decompiler` ... `py314Decompiler`)
are the only decompilers used.
"""

import os
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
    versions = ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14")
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
            import py_compile
            src_path = os.path.join(folder, version + ".py")
            with open(src_path, "w", encoding="utf-8") as f:
                f.write(sample)
            py_compile.compile(src_path, cfile=target, doraise=True)
            # decompile with matching folder
            import importlib
            mod = importlib.import_module("py%sDecompiler" % version.replace(".", ""))
            data = mod.decompile(open(target, "rb"))
            # Actually decompile needs code object, not file path; use parser
            from tests import cases
            from tests.equivalence import version_of
            import importlib
            parser_mod = importlib.import_module("py%sDecompiler.pyc_parser" % version.replace(".", ""))
            parsed = parser_mod.PyCParser.parse_file(target)
            rebuilt = mod.decompile(parsed.code)
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
        print("supported versions (folders):")
        versions = ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14")
        for v in versions:
            folder = "py%sDecompiler" % v.replace(".", "")
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
