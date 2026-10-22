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
debug_file = os.path.join(tempfile.gettempdir(), "d1debug_all.py")

# Write inner script directly to avoid f-string/format issues
inner = []
inner.append('import sys, os')
inner.append('sys.path.insert(0, r"' + os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pyvers') + r'")')
inner.append('sys.path.insert(0, r"' + os.path.dirname(os.path.abspath(__file__)) + r'")')
inner.append('from worker import load_code')
inner.append('from decomp311 import Rewriter, _exception_entries')
inner.append('')
inner.append('code = load_code(r"' + path + '", ' + str(header.payload_offset) + ')')
inner.append('rewriter = Rewriter(code)')
inner.append('')
inner.append('entries = list(_exception_entries(code))')
inner.append('print("Exception table entries:")')
inner.append('for e in entries:')
inner.append('    print("  start=%d end=%d target=%d depth=%d" % (e.start, e.end, e.target, e.depth))')
inner.append('')
inner.append('print("\\nAll raw instructions:")')
inner.append('for i, raw in enumerate(rewriter.raw):')
inner.append('    print("  [%3d] offset=%3d op=%-30s arg=%s argval=%r" % (i, raw.offset, raw.opname, raw.arg, raw.argval))')
inner.append('')
inner.append('print("\\n_retret:")')
inner.append('for off, val in getattr(rewriter, "_retarget", {}).items():')
inner.append('    print("  %d -> %d" % (off, val))')
inner.append('')
inner.append('print("\\n_tails_at_merge:")')
inner.append('for off, vals in getattr(rewriter, "_tails_at_merge", {}).items():')
inner.append('    print("  %d: %s" % (off, [(v.offset, v.opname) for v in vals]))')
inner.append('')
inner.append('print("\\n_drops:")')
inner.append('print(repr(rewriter._drops))')
inner.append('')

with open(debug_file, 'w') as f:
    f.write('\n'.join(inner))

result = subprocess.run([interp_path, debug_file], capture_output=True, text=True, timeout=30)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr[:2000])
