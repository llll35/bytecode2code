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

ver = '3.12'
path = os.path.join(tempfile.gettempdir(), "d1debug_%s.pyc" % ver)
pyvers.compile_source(src, path, version=ver)
header = pyvers.read_header(path)
interp_path = interp.interpreter_path(ver)
debug_file = os.path.join(tempfile.gettempdir(), "d1debug_%s_all.py" % ver)

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
inner.append('for e in entries:')
inner.append('    print("entry start=%d end=%d target=%d depth=%d" % (e.start, e.end, e.target, e.depth))')
inner.append('')
inner.append('for i, raw in enumerate(rewriter.raw):')
inner.append('    print("  [%3d] offset=%3d op=%-30s arg=%s argval=%r" % (i, raw.offset, raw.opname, raw.arg, raw.argval))')
inner.append('')
inner.append('print("\\n_retret:", dict(getattr(rewriter, "_retarget", {})))')
inner.append('print("_tails_at_merge:", {k: [(v.offset, v.opname) for v in vs] for k, vs in getattr(rewriter, "_tails_at_merge", {}).items()})')
inner.append('print("_drops:", repr(rewriter._drops))')
inner.append('print("try_closes:", repr(rewriter.try_closes))')
inner.append('print("try_setups:", repr(rewriter.try_setups))')
inner.append('')
inner.append('print("\\n_merge_offset for each entry:")')
inner.append('for e in entries:')
inner.append('    m = rewriter._merge_offset(e)')
inner.append('    print("  entry(start=%d end=%d target=%d): merge=%d" % (e.start, e.end, e.target, m))')
inner.append('')
inner.append('# Now run and show output')
inner.append('out = rewriter.run()')
inner.append('print("\\nOutput instructions:")')
inner.append('for ins in out:')
inner.append('    print("  offset=%3d op=%-30s arg=%s argval=%r" % (ins.offset, ins.opname, ins.arg, ins.argval))')
inner.append('')

with open(debug_file, 'w') as f:
    f.write('\n'.join(inner))

result = subprocess.run([interp_path, debug_file], capture_output=True, text=True, timeout=30)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr[:2000])
