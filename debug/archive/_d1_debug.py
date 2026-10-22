"""D1 debug: inspect 3.11/3.12 module-level try/except bytecode."""
import os
import sys
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pyvers  # noqa: E402
from pyvers import interp  # noqa: E402

src = """\
try:
    x = 1
except Exception:
    x = 2

class Foo:
    pass
"""

def run_debug(ver):
    folder = tempfile.mkdtemp(prefix=f"d1debug_{ver}_")
    path = os.path.join(folder, "m.pyc")
    pyvers.compile_source(src, path, version=ver)

    with open(path, "rb") as f:
        magic = f.read(4)
        flags = int.from_bytes(f.read(4), "little")
        timestamp = int.from_bytes(f.read(4), "little")
        size = int.from_bytes(f.read(4), "little")
        payload_offset = f.tell()
        raw = f.read()

    print(f"\n=== Python {ver} ===")
    print(f"Magic: {magic.hex()}, payload_offset={payload_offset}, raw_size={len(raw)}")

    interp_path = interp.interpreter_path(ver)
    if not interp_path:
        print(f"No interpreter for {ver}")
        return

    debug_script = f"""
import sys, os
sys.path.insert(0, r"{os.path.join(HERE, 'pyvers')}")
sys.path.insert(0, r"{HERE}")
from worker import load_code
from bytecode2code.disassembler import Disassembler
code = load_code(r"{path}", {payload_offset})
print(f"Code name: {{code.co_name}}")
print(f"co_flags={{code.co_flags}}, firstlineno={{code.co_firstlineno}}")
if hasattr(code, 'co_exceptiontable'):
    data = code.co_exceptiontable
    print(f"Exception table raw bytes: {{data.hex() if data else 'empty'}}")
    import dis as dis_module
    parser = getattr(dis_module, '_parse_exception_table', None)
    if parser:
        for i, e in enumerate(parser(code)):
            kind_str = ', kind=' + str(e.kind) if hasattr(e, 'kind') else ''
            print(f"  ExcEntry {{i}}: start={{e.start}}, end={{e.end}}, target={{e.target}}, depth={{e.depth}}{{kind_str}}")
d = Disassembler()
for inst in d.disassemble(code):
    print(f"  {{inst.offset:4d}}: {{inst.opname}} {{inst.argval if inst.argval else ''}}")
"""
    debug_file = os.path.join(folder, "debug.py")
    with open(debug_file, "w") as f:
        f.write(debug_script)
    result = subprocess.run([interp_path, debug_file], capture_output=True, text=True, timeout=30)
    print(result.stdout)
    if result.stderr:
        print(f"STDERR: {result.stderr[:500]}")

for ver in ("3.9", "3.10", "3.11", "3.12"):
    run_debug(ver)
