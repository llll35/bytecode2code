"""Debug: trace _merge_offset for 3.12 module-level try/except."""
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
debug_file = os.path.join(tempfile.gettempdir(), "d1debug_merge.py")
with open(debug_file, 'w') as f:
    f.write(f'''
import sys, os
sys.path.insert(0, r"{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pyvers')}")
sys.path.insert(0, r"{os.path.dirname(os.path.abspath(__file__))}")
from worker import load_code
from decomp311 import Rewriter, _exception_entries, _HANDLER_NOISE

code = load_code(r"{path}", {header.payload_offset})
rewriter = Rewriter(code)

entries = list(_exception_entries(code))
print("All entries:")
for e in entries:
    print(f"  start={{e.start}}, end={{e.end}}, target={{e.target}}, depth={{e.depth}}")

# Manually compute merge offset for entry(target=30)
entry = entries[0]
print(f"\\nComputing merge for entry(start={{entry.start}}, end={{entry.end}}, target={{entry.target}})")
end = max(other.end for other in entries if other.target >= entry.target)
print(f"  max end = {{end}}")

raw_list = rewriter.raw
index = 0
while index < len(raw_list) and raw_list[index].offset < end:
    index += 1
print(f"  after scan to end={{end}}: index={{index}}, offset={{raw_list[index].offset if index < len(raw_list) else 'END'}}")

print(f"  Scanner loop - checking from index={{index}}:")
while index < len(raw_list):
    op = raw_list[index].opname
    off = raw_list[index].offset
    in_noise = op in _HANDLER_NOISE
    is_reraise = op == 'RERAISE'
    print(f"    index={{index}} offset={{off}} op={{op}} noise={{in_noise}} reraise={{is_reraise}}")
    if in_noise or is_reraise:
        index += 1
    else:
        break
print(f"  final index={{index}}, offset={{raw_list[index].offset if index < len(raw_list) else 'END'}}")
print(f"  merge_offset = {{raw_list[index].offset if index < len(raw_list) else raw_list[-1].offset}}")

# Check what the actual rewriter returns
actual = rewriter._merge_offset(entry)
print(f"  rewriter._merge_offset = {{actual}}")
''')

result = subprocess.run([interp_path, debug_file], capture_output=True, text=True, timeout=30)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr[:1000])
