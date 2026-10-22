import sys, dis, importlib.util, traceback

src = """
try:
    x = 1
except Exception:
    x = 2

class Foo:
    pass
"""

def disasm_code(code_obj, label=''):
    print(f'=== {label} ===')
    print(f'  co_exceptiontable: {getattr(code_obj, "co_exceptiontable", None)}')
    print(f'  co_consts: {code_obj.co_consts}')
    for i, inst in enumerate(dis.get_instructions(code_obj)):
        print(f'  {inst.offset:4d}: {inst.opname:30s} {inst.argval or ""}')

for ver in ['3.9', '3.10', '3.11', '3.12']:
    try:
        v = int(ver.split('.')[1])
        args = [sys.executable, f'-{v}']
        if v >= 11:
            args.append('-X' + 'utf8')  # avoid encoding issue
        import subprocess
        py_cmd = sys.executable
        r = subprocess.run(
            [py_cmd, '-c',
             f'''
import sys, marshal
src = {repr(src)}
co = compile(src, "<test>", "exec")
f = open("d:/py/bytecode2code/_tmp_{ver}.pyc", "wb")
f.write(marshal.dumps(co))
f.close()
print("OK")
'''],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            print(f'{ver}: compile error: {r.stderr}')
            continue

        # Load the compiled code using target Python
        r2 = subprocess.run(
            [py_cmd, f'-{v}', '-c',
             f'''
import marshal, dis
with open("d:/py/bytecode2code/_tmp_{ver}.pyc", "rb") as f:
    co = marshal.load(f)
for inst in dis.get_instructions(co):
    print(f"  {{inst.offset:4d}}: {{inst.opname:30s}} {{inst.argval or ''}}")
if hasattr(co, "co_exceptiontable"):
    print("exceptiontable:")
    for e in co.co_exceptiontable:
        print(f"  start={{e.start}} end={{e.end}} target={{e.target}} depth={{e.depth}}")
else:
    print("no exceptiontable (3.9/3.10)")
'''],
            capture_output=True, text=True
        )
        print(f'--- {ver} ---')
        print(r2.stdout[:3000])
        if r2.stderr:
            print('STDERR:', r2.stderr[:500])
    except Exception as e:
        print(f'{ver}: {e}')
        traceback.print_exc()
