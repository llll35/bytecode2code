"""Scratch: run the flow corpus at every embedded interpreter, write one report.

    embed_python/python-3.9/python.exe _scratch/flow_all.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSIONS = ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14", "3.15")

out_path = os.path.join(ROOT, "_scratch", "flow_all.txt")
lines = []
for version in VERSIONS:
    exe = os.path.join(ROOT, "embed_python", "python-" + version, "python.exe")
    if not os.path.isfile(exe):
        lines.append("==== %s ====\n  (no interpreter)" % version)
        continue
    try:
        completed = subprocess.run(
            [exe, os.path.join(ROOT, "_scratch", "flow.py")],
            cwd=ROOT, capture_output=True, text=True, timeout=240)
        body = completed.stdout or ""
        tail = (completed.stderr or "").strip().splitlines()[-3:]
        lines.append("==== %s ====\n%s%s" % (
            version, body.rstrip(),
            ("\nERR:" + " | ".join(tail)) if tail else ""))
    except subprocess.TimeoutExpired:
        lines.append("==== %s ====\n  TIMEOUT" % version)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

print("\n".join(lines))
