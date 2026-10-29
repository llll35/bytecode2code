"""Scratch: run selected flow probes (or all) under the running interpreter.

    python _scratch/flow.py                 # every flow probe
    python _scratch/flow.py finally_return  # only names containing this
"""
import os
import py_compile
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.cases import FLOW_PROBES
from tests.equivalence import compare
from tests.test_roundtrip import _parser, decompile_sample, Result

selected = sys.argv[1:] or list(FLOW_PROBES)
ok = 0
with tempfile.TemporaryDirectory() as tmp:
    for name in selected:
        source = FLOW_PROBES[name]
        src_path = os.path.join(tmp, "%s.py" % name)
        pyc_path = os.path.join(tmp, "%s.pyc" % name)
        with open(src_path, "w", encoding="utf-8") as handle:
            handle.write(source)
        py_compile.compile(src_path, cfile=pyc_path, doraise=True)
        try:
            out = decompile_sample(pyc_path)
            parsed = _parser("%d.%d" % sys.version_info[:2]).PyCParser.parse_file(pyc_path)
            diffs = compare(parsed.code, compile(out, name + ".py", "exec"))
        except Exception as exc:
            out, diffs = None, ["%s: %s" % (type(exc).__name__, exc)]
        if diffs:
            print("  %-24s DIFF" % name)
            for line in diffs[:4]:
                print("      " + line)
            if len(diffs) > 4:
                print("      ... %d more" % (len(diffs) - 4))
            if "-v" in os.environ.get("FLOW VERBOSE", ""):
                print(out)
        else:
            ok += 1
            print("  %-24s OK" % name)
print("%d/%d identical (python %s)" % (ok, len(selected), sys.version.split()[0]))
