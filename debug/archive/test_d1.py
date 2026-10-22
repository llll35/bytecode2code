import sys
sys.path.insert(0, '.')
sys.path.insert(0, './pyvers')
from pyvers import compile_source
import tempfile
import os

code = '''
try:
    x = 1
except Exception:
    x = 2

class Foo:
    pass
'''

# Compile with Python 3.12
with tempfile.TemporaryDirectory() as tmpdir:
    pyc_path = os.path.join(tmpdir, 'test.pyc')
    compile_source(code, pyc_path, version='3.12')
    
    # Now decompile
    from pyvers import dispatch
    # Use disassemble to see the rewritten bytecode
    result = dispatch.disassemble(pyc_path)
    print('=== Full result ===')
    print(result)