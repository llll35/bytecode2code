"""Decompile every sample, recompile the result, and compare code objects.

This is the core guarantee of the project: decompiling a ``.pyc`` and
recompiling the output must yield a code object indistinguishable from the
original.  A sample passes when its instruction stream, constants, names and
locals all match, at every nesting depth.
"""

import os
import py_compile
import sys
import tempfile
from typing import List, NamedTuple, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bytecode2code.pyc_parser import PyCParser
from pyvers.decomp_compat import make_decompiler
from tests.cases import FILE_SAMPLES, OUTPUTS, PROBES, SAMPLES
from tests.equivalence import compare


class Result(NamedTuple):
    name: str
    ok: bool
    diffs: List[str]


def decompile_sample(pyc_path: str) -> str:
    """Decompile *pyc_path* with the reader that matches its bytecode.

    ``bytecode2code.main.decompile_file`` always drives the 3.9 reader, which
    cannot follow the exception tables 3.11 introduced.  The corpus spans
    versions, so the version-aware factory is what picks the right
    back-translator for each sample.
    """
    parsed = PyCParser.parse_file(pyc_path)
    return make_decompiler(parsed.python_version).decompile(parsed.code)


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

    return Result(name, not (diffs := compare(PyCParser.parse_file(pyc_path).code, recompiled)), diffs)


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
        results.append(_check(name, path, decompile_sample(path), keep=True))
    return results


def run_probes() -> List[Result]:
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, source in PROBES.items():
            src_path = os.path.join(tmp, "%s.py" % name)
            pyc_path = os.path.join(tmp, "%s.pyc" % name)
            with open(src_path, "w", encoding="utf-8") as f:
                f.write(source)
            py_compile.compile(src_path, cfile=pyc_path, doraise=True)
            results.append(_check("probe_" + name, pyc_path, decompile_sample(pyc_path), keep=False))
    return results


def run() -> List[Result]:
    return run_file_samples() + run_probes()


if __name__ == "__main__":
    for result in run():
        print("%-24s %s" % (result.name, "OK" if result.ok else "DIFF"))
        for diff in result.diffs[:4]:
            print("    " + diff)
