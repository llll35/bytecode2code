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

path = os.path.join(tempfile.gettempdir(), "d1test312.pyc")
pyvers.compile_source(src, path, version="3.12")
header = pyvers.read_header(path)

interp_path = interp.interpreter_path("3.12")
debug_file = os.path.join(tempfile.gettempdir(), "d1test_decomp_full.py")

inner = []
inner.append('import sys, os')
inner.append('sys.path.insert(0, r"' + os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pyvers') + r'")')
inner.append('sys.path.insert(0, r"' + os.path.dirname(os.path.abspath(__file__)) + r'")')
inner.append('from worker import load_code')
inner.append('from decomp_compat import make_decompiler')
inner.append('code = load_code(r"' + path + '", ' + str(header.payload_offset) + ')')
inner.append('dec = make_decompiler("3.12")')
inner.append('')
inner.append('# Debug the decompile process')
inner.append('from bytecode2code import disasm')
inner.append('instrs = dec.dis.disassemble(code)')
inner.append('print("Disassembled instructions:")')
inner.append('for i, ins in enumerate(instrs):')
inner.append('    print("  [%3d] %s" % (i, ins))')
inner.append('')
inner.append('result = dec.decompile(code)')
inner.append('print("RESULT:")')
inner.append('print(result)')

with open(debug_file, 'w') as f:
    f.write('\n'.join(inner))

result2 = subprocess.run([interp_path, debug_file], capture_output=True, text=True, timeout=30)
print(result2.stdout)
if result2.stderr:
    print("STDERR:", result2.stderr[-3000:])
