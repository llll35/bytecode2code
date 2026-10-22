"""D1: 3.12 module-level try/except swallows subsequent definitions."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pyvers  # noqa: E402

CASES = {
    "module try/except + class": """\
try:
    x = 1
except Exception:
    x = 2

class Foo:
    pass
""",
    "module try/except + def": """\
try:
    x = 1
except Exception:
    x = 2

def bar():
    return x
""",
    "module try/except + import + def": """\
try:
    import os
except Exception:
    pass

def baz():
    return 1
""",
}

def run(source, version):
    folder = tempfile.mkdtemp(prefix="d1_")
    path = os.path.join(folder, "m.pyc")
    pyvers.compile_source(source, path, version=version)
    return pyvers.decompile(path)["source"]

def main():
    for name in sorted(CASES):
        print("=" * 60)
        print(f"### {name}")
        print("--- source")
        print(CASES[name].rstrip())
        for version in ("3.9", "3.10", "3.11", "3.12"):
            try:
                out = run(CASES[name], version)
                print(f"--- {version}")
                print(out.rstrip() or "<<EMPTY>>")
            except Exception as exc:
                print(f"--- {version} ERROR: {exc}")

if __name__ == "__main__":
    main()
