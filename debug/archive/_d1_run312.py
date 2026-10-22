import sys, os, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pyvers'))
import pyvers
from pyvers import interp
from bytecode2code import Decompiler

src = """\
try:
    x = 1
except Exception:
    x = 2

class Foo:
    pass
"""

path = os.path.join(tempfile.gettempdir(), "d1test312.pyc")
pyvers.compile_source(src, path, version="3.12")
header = pyvers.read_header(path)

interp_path = interp.interpreter_path("3.12")
debug_file = os.path.join(tempfile.gettempdir(), "d1test_decomp.py")

inner = []
inner.append('import sys, os')
inner.append('sys.path.insert(0, r"' + os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pyvers') + r'")')
inner.append('sys.path.insert(0, r"' + os.path.dirname(os.path.abspath(__file__)) + r'")')
inner.append('from worker import load_code')
inner.append('from decomp311 import Rewriter')
inner.append('from bytecode2code import Decompiler')
inner.append('code = load_code(r"' + path + '", ' + str(header.payload_offset) + ')')
inner.append('rewriter = Rewriter(code)')
inner.append('result = rewriter.run()')
inner.append('print("OUTPUT count:", len(result))')
inner.append('for i, inst in enumerate(result):')
inner.append('    print("  [%3d] offset=%3d op=%-30s arg=%s argval=%r jump_target=%s" % (i, inst.offset, inst.opname, inst.arg, inst.argval, inst.is_jump_target))')
inner.append('print()')
inner.append('print("Jump targets:", [i for i, inst in enumerate(result) if inst.is_jump_target])')
inner.append('print("Offsets:", [inst.offset for inst in result])')
inner.append('print()')
inner.append('dec = Decompiler()')
inner.append('src_out = dec.decompile(result)')
inner.append('print("RESULT:")')
inner.append('print(src_out)')

with open(debug_file, 'w') as f:
    f.write('\n'.join(inner))

result = subprocess.run([interp_path, debug_file], capture_output=True, text=True, timeout=30)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr[-2000:])
