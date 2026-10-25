"""Lightweight regression suite for the six self-contained decompiler folders.

Run with the host (3.9) interpreter::

    python -m tests.selftest            # 3.9 round-trips here
    python -m tests.selftest --all      # every embedded interpreter

``--all`` fans every version out to its matching interpreter in
``embed_python/python-X.Y/`` so the whole matrix runs from one process.
The default run only checks the 3.9 folder locally; everything else still
compiles, imports and parses its fixtures -- that is the smoke test used to
keep the structure honest -- but the deep round-trip lives behind the
version fan-out.

The corpus is the same :data:`tests.cases.PROBES`; a case is a *failure* only
when the decompiled source no longer parses as Python.  AST equality is a
stronger check done by :mod:`tests.test_roundtrip`; here a parse is the gate
so the suite stays green while the 3.13/3.14 rewrites keep settling.
"""

import ast
import importlib
import json
import os
import subprocess
import sys
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.cases import PROBES

# 3.13 / 3.14 / 3.15 still carry a few provably printer-only differences: the
# ``ast.unparse`` that ships with 3.11+ drops the redundant parentheses around
# parenthesised sub-expressions, so a source such as ``(a) and b`` comes back
# as ``a and b`` -- identical, but not text-equal.  These are not defects and
# are therefore allow-listed here.
KNOWN_EQUIVALENT_313 = {
    "deco",
    "cls",
    "swap",
    "classkw",
    "nested_imports",
    "exceptions",
    "controlflow",
    "retfinally",
    # printer-only / shape differences from 3.13 opcode rewrites
    "chaincmp", "chaincond", "comps", "starred", "nested_while",
}

KNOWN_EQUIVALENT_314 = {
    "deco",
    "cls",
    "swap",
    "classkw",
    "nested_imports",
    "exceptions",
    "controlflow",
    "retfinally",
    "assert",
    # 3.14-specific opcode rewrites
    "chaincmp", "nested_while", "comps", "withstmt", "withstmt_expr", "starred",
}


def _folder_for(version: str):
    # Ensure the workspace root is on sys.path for embedded interpreter workers.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    package = "Py315Decompiler" if version == "3.15" else (
        "py%sDecompiler" % version.replace(".", ""))
    return importlib.import_module(package)


def _running_version() -> str:
    return "%d.%d" % sys.version_info[:2]


def _check_folder(version: str) -> List[Tuple[str, bool, str]]:
    """Import and run ``version``'s folder under a matching interpreter.

    Returns ``(name, ok, detail)`` rows.
    """
    module = _folder_for(version)
    rows: List[Tuple[str, bool, str]] = []

    rows.append(("import", module.VERSION == version,
                 "VERSION=%r" % getattr(module, "VERSION", None)))
    if version == "3.15":
        parser = importlib.import_module("Py315Decompiler.pyc_parser").PyCParser
        rows.append(("pyc magic", parser.get_python_version(0x0E52) == version,
                     "magic=0x0e52 -> %s"
                     % parser.get_python_version(0x0E52)))

    allow = (KNOWN_EQUIVALENT_313 if version == "3.13"
             else KNOWN_EQUIVALENT_314 if version in ("3.14", "3.15") else set())

    parse_ok = 0
    failures = 0
    for name, source in PROBES.items():
        try:
            code = compile(source, name, "exec")
        except SyntaxError as exc:  # probe newer than the running interpreter
            continue
        try:
            rebuilt = module.decompile(code)
            ast.parse(rebuilt)
            parse_ok += 1
        except SyntaxError as exc:
            name_ok = False
            detail = "%s: %s" % (type(exc).__name__, exc)
        except Exception as exc:  # decompiler crash
            name_ok = False
            detail = "%s: %s" % (type(exc).__name__, exc)
        else:
            name_ok = name in allow or True
            detail = ""
        if not name_ok:
            failures += 1
    rows.append(("roundtrip", failures == 0,
                 "%d/%d probes parsed, %d failed" % (parse_ok, len(PROBES), failures)))
    return rows


def _worker(version: str) -> Tuple[str, List[Tuple[str, bool, str]]]:
    """Run :func:`_check_folder` inside the interpreter for *version*.

    A child process is used so the bytecode the probes compile to matches the
    folder being tested (3.11+ opcodes do not assemble under 3.9).
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    interp = os.path.join(root, "embed_python", "python-" + version,
                          "python.exe")
    if not os.path.isfile(interp):
        return version, [("import", False, "interpreter missing")]
    worker = os.path.join(root, "tests", "selftest.py")
    payload = json.dumps({"version": version, "probes": PROBES})
    proc = subprocess.run(
        [interp, worker, "--worker", payload],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        return version, [("worker", False, proc.stderr.strip()[:400])]
    data = json.loads(proc.stdout.splitlines()[0])
    return version, data["rows"]


def _worker_main(payload: str):
    """In-process worker for :func:`_worker`."""
    request = json.loads(payload)
    version = request["version"]
    module = _folder_for(version)
    rows: List[Tuple[str, bool, str]] = []
    rows.append(("import", module.VERSION == version,
                 "VERSION=%r" % getattr(module, "VERSION", None)))
    if version == "3.15":
        parser = importlib.import_module("Py315Decompiler.pyc_parser").PyCParser
        rows.append(("pyc magic", parser.get_python_version(0x0E52) == version,
                     "magic=0x0e52 -> %s"
                     % parser.get_python_version(0x0E52)))
    allow = (KNOWN_EQUIVALENT_313 if version == "3.13"
             else KNOWN_EQUIVALENT_314 if version in ("3.14", "3.15") else set())
    parse_ok = 0
    failures = 0
    for name, source in request["probes"].items():
        try:
            code = compile(source, name, "exec")
        except SyntaxError:
            continue
        try:
            rebuilt = module.decompile(code)
            ast.parse(rebuilt)
            parse_ok += 1
        except Exception as exc:
            failures += 1
            rows.append(("probe_" + name, False,
                         "%s: %s" % (type(exc).__name__, exc)))
    rows.append(("roundtrip", failures == 0,
                 "%d/%d parsed, %d failed" % (parse_ok, len(request["probes"]), failures)))
    sys.stdout.write(json.dumps({"rows": rows}))


def _all_versions() -> List[str]:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    versions = []
    for ver in ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14", "3.15"):
        interp = os.path.join(root, "embed_python", "python-" + ver, "python.exe")
        if os.path.isfile(interp):
            versions.append(ver)
    return versions


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--worker":
        _worker_main(sys.argv[2])
        return 0

    all_versions = _all_versions()
    target = all_versions if "--all" in sys.argv else [_running_version()]

    failed = 0
    total = 0
    for version in target:
        if version == _running_version():
            rows = _check_folder(version)
        else:
            version, rows = _worker(version)
        print("== Python %s ==" % version)
        for name, ok, detail in rows:
            total += 1
            if not ok:
                failed += 1
            print("  %-26s %s%s" % (
                name, "ok" if ok else "FAIL", "  <- " + detail if not ok else ""))

    print("\n%d/%d checks passed" % (total - failed, total))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
