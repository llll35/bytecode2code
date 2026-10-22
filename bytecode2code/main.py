import argparse
import os
import sys
import py_compile
import tempfile
import dis as _dis

from .errors import Bytecode2CodeError
from .pyc_parser import PyCParser, PyCFile, collect_code_objects
from .disassembler import Disassembler
from .decompiler import Decompiler


def decompile_file(path: str, output_file: str = None, verbose: bool = False) -> str:
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    pyc_file = PyCParser.parse_file(path)
    dec = Decompiler()
    source = dec.decompile(pyc_file.code)
    sub_objects = collect_code_objects(pyc_file.code)
    if verbose and len(sub_objects) > 1:
        parts = [source]
        for depth, code in sub_objects[1:]:
            if hasattr(code, "co_name") and hasattr(code, "co_code"):
                inner = dec._decompile_code_object(code, indent_level=0)
                parts.append("\n" + "#" * 60)
                parts.append(f"# Nested code object: {code.co_name} (depth={depth})")
                parts.append("#" * 60)
                parts.append("\n" + f"# --- {code.co_name} ---")
                parts.append(inner)
        source = "\n".join(parts)
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(source)
        print(f"Decompiled source written to: {output_file}")
    return source


def decompile_code(code, verbose: bool = False) -> str:
    dec = Decompiler()
    return dec.decompile(code)


def disassemble_file(path: str, output_file: str = None, show_header: bool = True) -> str:
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    pyc_file = PyCParser.parse_file(path)
    d = Disassembler()
    parts = []
    if show_header:
        parts.append("=" * 60)
        parts.append("PYC FILE HEADER")
        parts.append("=" * 60)
        parts.append(pyc_file.format_header())
        parts.append("")
    parts.append("=" * 60)
    parts.append(f"DISASSEMBLY: {getattr(pyc_file.code, 'co_name', '<code>')}")
    parts.append("=" * 60)
    parts.append(d.disassemble_to_str(pyc_file.code, show_header=True, show_lineno=True))
    sub_objects = collect_code_objects(pyc_file.code)
    for depth, code in sub_objects[1:]:
        if hasattr(code, "co_code"):
            parts.append("")
            parts.append("=" * 60)
            prefix = "  " * depth
            parts.append(f"{prefix}DISASSEMBLY: {getattr(code, 'co_name', '<code>')} (depth={depth})")
            parts.append("=" * 60)
            parts.append(d.disassemble_to_str(code, show_header=True, show_lineno=True))
    result = "\n".join(parts)
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"Disassembly written to: {output_file}")
    return result


def disassemble_code(code, show_header: bool = True) -> str:
    d = Disassembler()
    return d.disassemble_to_str(code, show_header=show_header)


def compile_source_to_pyc(source_code: str, pyc_path: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
        tmp.write(source_code)
        tmp_path = tmp.name
    try:
        py_compile.compile(tmp_path, cfile=pyc_path, dfile="<test-source>", doraise=True)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def show_info(path: str, output_file: str = None) -> str:
    pyc_file = PyCParser.parse_file(path)
    lines = []
    lines.append("=" * 60)
    lines.append("PYC FILE INFORMATION")
    lines.append("=" * 60)
    lines.append(f"File: {path}")
    lines.append(f"Size: {len(pyc_file.raw_data)} bytes")
    lines.append("")
    lines.append(pyc_file.format_header())
    lines.append("")
    code = pyc_file.code
    lines.append(f"Code object: {getattr(code, 'co_name', '?')}")
    lines.append(f"  co_filename: {getattr(code, 'co_filename', '?')}")
    lines.append(f"  co_firstlineno: {getattr(code, 'co_firstlineno', '?')}")
    lines.append(f"  co_argcount: {getattr(code, 'co_argcount', 0)}")
    lines.append(f"  co_kwonlyargcount: {getattr(code, 'co_kwonlyargcount', 0)}")
    lines.append(f"  co_nlocals: {getattr(code, 'co_nlocals', 0)}")
    lines.append(f"  co_flags: {getattr(code, 'co_flags', 0):#x}")
    lines.append(f"  co_code length: {len(getattr(code, 'co_code', b''))} bytes")
    lines.append(f"  co_consts count: {len(getattr(code, 'co_consts', ()))}")
    lines.append(f"  co_names count: {len(getattr(code, 'co_names', ()))}")
    lines.append(f"  co_varnames count: {len(getattr(code, 'co_varnames', ()))}")
    nested = collect_code_objects(code)
    lines.append(f"  nested code objects: {len(nested) - 1}")
    for depth, obj in nested[1:]:
        lines.append(f"    [depth {depth}] {getattr(obj, 'co_name', '?')} @ line {getattr(obj, 'co_firstlineno', '?')}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bytecode2code",
        description="Python .pyc file decompiler - disassemble and decompile Python bytecode",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    decompile_parser = subparsers.add_parser("decompile", aliases=["d"], help="Decompile .pyc file to source code")
    decompile_parser.add_argument("input", help="Input .pyc file path")
    decompile_parser.add_argument("-o", "--output", help="Output source file path (default: stdout)")
    decompile_parser.add_argument("-v", "--verbose", action="store_true", help="Include verbose output")

    disas_parser = subparsers.add_parser("disassemble", aliases=["dis"], help="Disassemble .pyc file bytecode")
    disas_parser.add_argument("input", help="Input .pyc file path")
    disas_parser.add_argument("-o", "--output", help="Output file path (default: stdout)")
    disas_parser.add_argument("--no-header", action="store_true", help="Skip pyc header info")

    info_parser = subparsers.add_parser("info", aliases=["i"], help="Show .pyc file information")
    info_parser.add_argument("input", help="Input .pyc file path")

    demo_parser = subparsers.add_parser("demo", help="Run a demo: compile sample source and decompile")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command in ("decompile", "d"):
        _run(decompile_file, args.input, args.output, verbose=args.verbose)
        return 0

    if args.command in ("disassemble", "dis"):
        _run(disassemble_file, args.input, args.output,
             show_header=not args.no_header)
        return 0

    if args.command in ("info", "i"):
        _run(show_info, args.input)
        return 0

    if args.command == "demo":
        run_demo()
        return 0

    parser.print_help()
    return 1


#: Exit status used for every error the package raises on purpose.
EXIT_ERROR = 1


def _run(handler, path, output_file=None, **kwargs) -> None:
    """Call *handler* and print its result, or report the failure cleanly.

    Everything the library raises on purpose -- an unreadable ``.pyc``, a
    version this interpreter cannot decode -- becomes a one-line message and a
    non-zero status.  A traceback is reserved for actual bugs, which is what
    makes the two distinguishable when reading CI output.
    """
    try:
        result = handler(path, output_file, **kwargs)
    except (Bytecode2CodeError, FileNotFoundError, IsADirectoryError,
            PermissionError) as exc:
        sys.stderr.write("error: %s\n" % exc)
        raise SystemExit(EXIT_ERROR)
    if result is not None and not output_file:
        print(result)

def run_demo():
    sample_source = '''
"""Module docstring for demo."""

CONSTANT = 42

def add(a, b):
    """Add two numbers."""
    result = a + b
    return result

def greet(name: str) -> str:
    """Return a greeting."""
    message = f"Hello, {name}!"
    print(message)
    return message

class Counter:
    """A simple counter."""
    def __init__(self, start=0):
        self.value = start

    def increment(self, step=1):
        self.value += step
        return self.value

def compute_factorial(n):
    """Compute n! using a loop."""
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result

def check_value(x):
    if x > 100:
        return "large"
    elif x > 50:
        return "medium"
    else:
        return "small"

if __name__ == "__main__":
    c = Counter()
    c.increment(5)
    print("Counter:", c.value)
    print("Factorial(5):", compute_factorial(5))
    print("add(2, 3):", add(2, 3))
    print(greet("World"))
    print("check_value(75) =", check_value(75))
'''
    print("=" * 60)
    print("BYTECODE2CODE DEMO")
    print("=" * 60)
    with tempfile.TemporaryDirectory() as tmpdir:
        pyc_path = os.path.join(tmpdir, "demo.pyc")
        print("\n[1] Compiling sample source to .pyc ...")
        compile_source_to_pyc(sample_source, pyc_path)
        print(f"    -> {pyc_path} ({os.path.getsize(pyc_path)} bytes)")

        print("\n[2] PYC file info:")
        print(show_info(pyc_path))

        print("\n[3] Disassembly (main module, first 40 lines):")
        disas = disassemble_file(pyc_path)
        dis_lines = disas.split("\n")
        for line in dis_lines[:40]:
            print("    " + line)
        if len(dis_lines) > 40:
            print(f"    ... ({len(dis_lines) - 40} more lines)")

        print("\n[4] Decompiled source:")
        print("-" * 60)
        try:
            src = decompile_file(pyc_path, verbose=False)
            print(src)
        except Exception as e:
            print(f"Decompiler error: {e}")
            import traceback
            traceback.print_exc()
        print("-" * 60)
    print("\nDemo completed successfully.")


if __name__ == "__main__":
    sys.exit(main())
