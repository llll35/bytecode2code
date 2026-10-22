"""Round-trip every file sample under an interpreter that matches its bytecode."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests import cases
from tests.equivalence import version_of

OUT = sys.argv[1] if len(sys.argv) > 1 else None

if OUT:
    # ---- child mode: run the samples for the version named in the env ----
    version = os.environ["BYTECODE2CODE_TESTS_GROUP"]
    from bytecode2code.main import decompile_file
    from bytecode2code.pyc_parser import PyCParser
    from tests.equivalence import compare
    import py_compile

    payload = []
    for name, pyc_name in cases.FILE_SAMPLES.items():
        path = os.path.join(cases.SAMPLES, pyc_name)
        if not os.path.exists(path):
            continue
        if version_of(path) != version:
            continue
        try:
            source = decompile_file(path)
        except Exception as exc:
            payload.append({"name": name, "ok": False,
                            "diffs": ["decompile failed: %s: %s" % (type(exc).__name__, exc)]})
            continue
        try:
            recompiled = compile(source, name + ".py", "exec")
        except SyntaxError as exc:
            payload.append({"name": name, "ok": False,
                            "diffs": ["output does not parse: %s" % exc]})
            continue
        diffs = compare(PyCParser.parse_file(path).code, recompiled)
        payload.append({"name": name, "ok": not diffs, "diffs": diffs})
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    sys.exit(0)

# ---- parent mode ----
from pyvers import interp

groups = {}
for name, pyc_name in cases.FILE_SAMPLES.items():
    path = os.path.join(cases.SAMPLES, pyc_name)
    if os.path.exists(path):
        groups.setdefault(version_of(path), []).append(name)

print("sample groups:", groups)
tmp = tempfile.mkdtemp()
for version, names in sorted(groups.items()):
    interpreter = interp.interpreter_path(version)
    if interpreter is None:
        print("  %-6s NO INTERPRETER (samples %s)" % (version, names))
        continue
    out_path = os.path.join(tmp, "res_%s.json" % version)
    env = dict(os.environ,
               BYTECODE2CODE_TESTS_GROUP=version,
               BYTECODE2CODE_TESTS_OUT=out_path)
    script = os.path.join(ROOT, "tests", "run_probe.py")
    proc = subprocess.run([interpreter, script, out_path], env=env,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        print("  %-6s CHILD FAILED rc=%s" % (version, proc.returncode))
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
        continue
    with open(out_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    for item in payload:
        print("  %-6s %-20s %s" % (version, item["name"], "OK" if item["ok"] else "DIFF"))
        for diff in item["diffs"][:6]:
            print("        " + diff)
