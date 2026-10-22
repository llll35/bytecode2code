"""Debug: trace rewriter internals for 3.12 module-level try/except."""
import sys, os, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pyvers'))
import pyvers
from pyvers import interp

src = """\
try:
    x = 1
except Exception:
    x = 2

class Foo:
    pass
"""

path = os.path.join(tempfile.gettempdir(), "d1debug_312.pyc")
pyvers.compile_source(src, path, version="3.12")
header = pyvers.read_header(path)

interp_path = interp.interpreter_path("3.12")
assert interp_path, "No 3.12 interpreter"

# Write debug script to temp file to avoid f-string escaping issues
debug_file = os.path.join(tempfile.gettempdir(), "d1debug_script.py")
with open(debug_file, 'w') as f:
    f.write(f'''
import sys, os
sys.path.insert(0, r"{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pyvers')}")
sys.path.insert(0, r"{os.path.dirname(os.path.abspath(__file__))}")
from worker import load_code
from decomp311 import Rewriter, _exception_entries

code = load_code(r"{path}", {header.payload_offset})
rewriter = Rewriter(code)

print("Exception entries:")
for entry in _exception_entries(code):
    print(f"  start={{entry.start}}, end={{entry.end}}, target={{entry.target}}, depth={{entry.depth}}")

tails = getattr(rewriter, '_tails_at_merge', {{}})
print(f"Instruction count: {{len(rewriter.raw)}}")
print(f"  _drops: {{sorted(rewriter._drops)}}")
print(f"  _retarget: {{rewriter._retarget}}")
print(f"  _tails_at_merge keys: {{list(tails.keys())}}")
if tails:
    for k, v in tails.items():
        print(f"    merge@{{k}}: offsets={{[i.offset for i in v]}}, opnames={{[i.opname for i in v]}}")

print()
print("=== Raw instructions ===")
for i, raw in enumerate(rewriter.raw):
    marker = ""
    if raw.offset in rewriter._drops:
        marker += " [DROP]"
    if raw.offset in rewriter._retarget:
        marker += f" [RETARGET->{{rewriter._retarget[raw.offset]}}]"
    if raw.offset in tails:
        marker += " [TAIL_SOURCE]"
    tail_info = ""
    for mk, mv in tails.items():
        if any(t.offset == raw.offset for t in mv):
            tail_info = f" [TAIL@{{mk}}]"
    av = str(raw.argval) if raw.argval is not None else ''
    av = av[:20]
    print(f"  {{i:3d}}: {{raw.offset:4d}}: {{raw.opname:<28}}{{av:<20}}{{marker}}{{tail_info}}")

print()
print("=== Rewritten instructions (run) ===")
out = rewriter.run()
for i, raw in enumerate(out):
    av = str(raw.argval) if raw.argval is not None else ''
    av = av[:20]
    print(f"  {{i:3d}}: {{raw.offset:4d}}: {{raw.opname:<28}}{{av:<20}}")
''')

result = subprocess.run([interp_path, debug_file], capture_output=True, text=True, timeout=30)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr[:1000])
