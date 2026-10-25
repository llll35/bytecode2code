"""Run the whole suite:  python -m tests.run  [--verbose]

The corpus is ``.pyc`` files, and ``marshal`` has no cross-version
compatibility, so a sample can only be read by the interpreter it was compiled
for.  The corpus is not a single version either -- the syntax demos are 3.9,
``prime.pyc`` is 3.12 -- so the runner fans out: one child process per version,
each reading its own samples, recompiling the result with the same interpreter
so the comparison is like-for-like, and round-tripping the source-only probes
as well.  Results come back as JSON and the parent prints one report.

The probes run at *every* version on purpose.  They are the only part of the
corpus that can exercise each back end (3.9, 3.10, 3.11, 3.12, 3.13 and 3.14 all
take different paths through the decompiler), and a probe that round-trips on
one version can still be wrong on another.
"""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import cases
from tests.equivalence import version_of

VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv

#: Every bytecode version the repository ships a self-contained decompiler
#: for.  The probes run at all of them; a sample only runs at the version that
#: wrote its ``.pyc``.
SUPPORTED_VERSIONS = ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14", "3.15")

#: Set in a child process: the bytecode version whose samples it owns.
GROUP_ENV = "BYTECODE2CODE_TESTS_GROUP"
#: Set in a child process: the file it writes its JSON payload to.
OUT_ENV = "BYTECODE2CODE_TESTS_OUT"


def _running_version() -> str:
    return "%d.%d" % sys.version_info[:2]


def _sample_versions() -> dict:
    """Sample name -> the bytecode version needed to read its ``.pyc``."""
    versions = {}
    for name, pyc_name in cases.FILE_SAMPLES.items():
        path = os.path.join(cases.SAMPLES, pyc_name)
        if not os.path.exists(path):
            continue
        found = version_of(path)
        if found:
            versions[name] = found
    return versions


def _interpreter_for(version: str):
    """Path to the embedded interpreter for *version*, or ``None``."""
    path = os.path.join(cases.ROOT, "embed_python", "python-" + version,
                        "python.exe")
    return path if os.path.isfile(path) else None


def _run_group(version: str) -> int:
    """Child entry point: round-trip *version*'s samples and the probes."""
    from tests import test_roundtrip

    names = [name for name, needed in _sample_versions().items()
             if needed == version]
    results = test_roundtrip.run_file_samples(names) + test_roundtrip.run_probes()
    with open(os.environ[OUT_ENV], "w", encoding="utf-8") as handle:
        json.dump([result._asdict() for result in results], handle)
    return 0


def _collect(version: str, workdir: str, index: int):
    """Round-trip results for *version*, in this process when possible."""
    from tests import test_roundtrip

    names = [name for name, needed in _sample_versions().items()
             if needed == version]
    if version == _running_version():
        return test_roundtrip.run_file_samples(names) + test_roundtrip.run_probes()

    interpreter = _interpreter_for(version)
    if interpreter is None:
        sys.stderr.write(
            "no embedded Python %s: skipping its samples\n" % version
        )
        return []

    out_path = os.path.join(workdir, "group_%d.json" % index)
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.py")
    env = dict(os.environ, **{GROUP_ENV: version, OUT_ENV: out_path})
    completed = subprocess.run([interpreter, script], env=env,
                               capture_output=True, text=True)
    if completed.returncode != 0:
        sys.stderr.write(
            "Python %s round-trip failed (exit %d)\n%s%s"
            % (version, completed.returncode,
               completed.stdout, completed.stderr)
        )
        return []
    with open(out_path, encoding="utf-8") as handle:
        return [test_roundtrip.Result(**item) for item in json.load(handle)]


def main() -> int:
    group = os.environ.get(GROUP_ENV)
    if group:
        return _run_group(group)

    from tests import test_ast

    versions = _sample_versions()
    ordered = [v for v in SUPPORTED_VERSIONS if _interpreter_for(v)]
    for version in versions.values():
        if version not in ordered:
            sys.stderr.write(
                "no embedded Python %s: skipping %s samples\n"
                % (version, version))

    print("=" * 60)
    print("ROUND-TRIP  (decompile -> recompile -> compare code objects)")
    print("=" * 60)

    total = 0
    failed = 0
    with tempfile.TemporaryDirectory() as workdir:
        for index, version in enumerate(ordered):
            print("\n-- Python %s --" % version)
            for result in _collect(version, workdir, index):
                total += 1
                if result.ok:
                    print("  %-24s OK" % result.name)
                    continue
                failed += 1
                print("  %-24s DIFF" % result.name)
                shown = result.diffs if VERBOSE else result.diffs[:2]
                for diff in shown:
                    print("      " + diff)
                if not VERBOSE and len(result.diffs) > len(shown):
                    print("      ... %d more" % (len(result.diffs) - len(shown)))

    print("\n%d/%d identical" % (total - failed, total))

    print()
    print("=" * 60)
    print("SOURCE FIDELITY  (AST diff against the original .py, comments ignored)")
    print("=" * 60)
    for item in test_ast.run():
        if item.note:
            print("  %-24s skipped: %s" % (item.name, item.note))
        elif not item.diff:
            print("  %-24s structurally identical" % item.name)
        else:
            print("  %-24s %d differing lines" % (item.name, len(item.diff)))
            if VERBOSE:
                for line in item.diff:
                    print("      " + line)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
