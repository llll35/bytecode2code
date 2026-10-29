"""Decompile every sample, recompile the result, and compare code objects.

This is the core guarantee of the project: decompiling a ``.pyc`` and
recompiling the output must yield a code object indistinguishable from the
original.  A sample passes when its instruction stream, constants, names and
locals all match, at every nesting depth.
"""

import importlib
import os
import py_compile
import sys
import tempfile
from typing import List, NamedTuple, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.cases import FILE_SAMPLES, FLOW_PROBES, OUTPUTS, PROBES, SAMPLES
from tests.equivalence import compare, version_of


def _package(version: str) -> str:
    """The self-contained folder for *version*.

    Every folder is named ``pyXYDecompiler``, 3.15 included; a capitalised
    variant does not import even though the Windows file system resolves it.
    """
    return "py%sDecompiler" % version.replace(".", "")


def _folder(version: str):
    """Import the self-contained decompiler for *version*."""
    return importlib.import_module(_package(version))


def _parser(version: str):
    return importlib.import_module(_package(version) + ".pyc_parser")


class Result(NamedTuple):
    name: str
    ok: bool
    diffs: List[str]


def decompile_sample(pyc_path: str) -> str:
    """Decompile *pyc_path* with the self-contained folder it belongs to.

    Each version folder carries its own reader, so the file's bytecode version
    selects it; the folder is imported from the running interpreter, which the
    runner guarantees is the matching one.
    """
    parsed = _parser(version_of(pyc_path)).PyCParser.parse_file(pyc_path)
    return _folder(parsed.python_version).decompile(parsed.code)


def _check(name: str, pyc_path: str, source: str, keep: bool) -> Result:
    """Round-trip one sample.

    ``keep`` decides whether the decompiled source is worth keeping on disk.
    The file samples are the project's showcase output, so they are written to
    ``debug/outputs``.  The probes exist only to be compared, and dumping
    eighteen of them there would bury the interesting ones.
    """
    if keep:
        out_path = os.path.join(OUTPUTS, "%s.py" % name)
        os.makedirs(OUTPUTS, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(source)

    try:
        recompiled = compile(source, name + ".py", "exec")
    except SyntaxError as exc:
        return Result(name, False, ["output does not parse: %s" % exc])

    parsed = _parser(version_of(pyc_path)).PyCParser.parse_file(pyc_path)
    return Result(name, not (diffs := compare(parsed.code, recompiled)), diffs)


def run_file_samples(names: Sequence[str] = None) -> List[Result]:
    """Round-trip the ``.pyc`` samples, or only *names* of them.

    Each sample has to be read -- and its output recompiled -- by an
    interpreter that speaks its bytecode version, so the caller is responsible
    for running this under the right one.
    """
    selected = FILE_SAMPLES if names is None else {
        name: FILE_SAMPLES[name] for name in names
    }
    results = []
    for name, pyc_name in selected.items():
        path = os.path.join(SAMPLES, pyc_name)
        try:
            results.append(_check(name, path, decompile_sample(path), keep=True))
        except Exception as exc:
            results.append(Result(name, False,
                                  ["%s: %s" % (type(exc).__name__, exc)]))
    return results


def _run_probe_set(probes: dict, prefix: str) -> List[Result]:
    """Round-trip a dict of source probes, one result per entry.

    Compiling and decompiling each probe is wrapped so that a single bad probe
    is reported as a failure instead of aborting the version group.  An abort
    here reads as "this version produced no results", which is how the 3.15
    group went unnoticed for a whole test cycle.
    """
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, source in probes.items():
            src_path = os.path.join(tmp, "%s.py" % name)
            pyc_path = os.path.join(tmp, "%s.pyc" % name)
            try:
                with open(src_path, "w", encoding="utf-8") as f:
                    f.write(source)
                py_compile.compile(src_path, cfile=pyc_path, doraise=True)
                results.append(_check(prefix + name, pyc_path,
                                      decompile_sample(pyc_path), keep=False))
            except Exception as exc:
                results.append(Result(prefix + name, False,
                                      ["%s: %s" % (type(exc).__name__, exc)]))
    return results


def run_probes() -> List[Result]:
    return _run_probe_set(PROBES, "probe_")


def run_flow_probes() -> List[Result]:
    """The control-flow corpus, reported apart from the main probe count."""
    return _run_probe_set(FLOW_PROBES, "flow_")


def run() -> List[Result]:
    return run_file_samples() + run_probes() + run_flow_probes()


if __name__ == "__main__":
    for result in run():
        print("%-24s %s" % (result.name, "OK" if result.ok else "DIFF"))
        for diff in result.diffs[:4]:
            print("    " + diff)
