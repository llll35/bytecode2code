import sys
sys.path.insert(0, '.')
from pyvers import dispatch, interp
import tempfile
import os
import subprocess

src = '''
try:
    x = 1
except Exception:
    x = 2

class Foo:
    pass
'''

with tempfile.TemporaryDirectory(prefix='test_') as folder:
    pyc = os.path.join(folder, 'm.pyc')
    dispatch.compile_source(src, pyc, version='3.12', dfile='<test>')
    
    runner = os.path.join(folder, 'r.py')
    with open(runner, 'w', encoding='utf-8') as f:
        f.write('''
import sys, os, marshal, dis
for p in (os.path.join(r"%ROOT%", "pyvers"), r"%ROOT%"):
    if p not in sys.path:
        sys.path.insert(0, p)
import decomp311
import subprocess
with open(sys.argv[1], "rb") as h:
    top = marshal.loads(h.read()[16:])
print("Top-level code:", top.co_name)
print("Exception entries:")
for e in decomp311._exception_entries(top):
    print(f"  start={e.start}, end={e.end}, target={e.target}, depth={e.depth}, lasti={e.lasti}")
r = decomp311.Rewriter(top)
shape = r.analyse()
print()
print("Raw instructions:")
for raw in r.raw:
    print(f"  offset={raw.offset}, opname={raw.opname}, argval={raw.argval}")
print()
print("_tails_at_merge:", getattr(r, '_tails_at_merge', 'NOT SET'))
print("_retarget:", getattr(r, '_retarget', 'NOT SET'))
print("_drops:", getattr(r, '_drops', 'NOT SET'))
'''.replace('%ROOT%', os.path.dirname(os.path.abspath(__file__))))
    
    proc = subprocess.run(
        [interp.interpreter_path('3.12'), runner, pyc],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    print(proc.stdout.decode('utf-8', 'replace'))