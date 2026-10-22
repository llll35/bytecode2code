"""Round-trip every probe case: decompile -> recompile -> compare code objects."""
import os
import py_compile
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _tc_probe import CASES  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
DEBUG = os.path.join(BASE, "debug")
VERIFIER = os.path.join(BASE, "_semcheck.py")

bad = []
for name, src in CASES.items():
    src_p = os.path.join(DEBUG, "_probe_%s.py" % name)
    src_c = os.path.join(DEBUG, "_probe_%s.pyc" % name)
    out_p = os.path.join(DEBUG, "_probeout_%s.py" % name)
    py_compile.compile(src_p, cfile=src_c, doraise=True)
    from bytecode2code.main import decompile_file
    text = decompile_file(src_c)
    with open(out_p, "w", encoding="utf-8") as f:
        f.write(text)
    r = subprocess.run(
        [sys.executable, VERIFIER, src_c, out_p],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    if not lines:
        print("%-10s DIFF  NO-OUTPUT  %s" % (name, r.stderr.strip().splitlines()[-1][:70] if r.stderr.strip() else ""))
        bad.append(name)
        continue
    tag = "PASS" if "IDENTICAL" in lines[-1] else "DIFF"
    detail = " ".join(lines[-1].split())[:88]
    print("%-10s %s  %s" % (name, tag, detail))
    if tag == "DIFF":
        bad.append(name)
        if os.environ.get("VERBOSE"):
            for ln in lines[:-1]:
                print("            " + ln)

print("\n%d/%d identical" % (len(CASES) - len(bad), len(CASES)))
