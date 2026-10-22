"""Decompile every sample pyc and recompile the result, then compare bytecode."""
import dis
import os
import sys

sys.path.insert(0, 'd:/py/bytecode2code')
sys.path.insert(0, 'd:/py/bytecode2code/debug')

from bytecode2code.pyc_parser import PyCParser
from bytecode2code.decompiler import Decompiler
from _semcheck import compare

ROOT = 'd:/py/bytecode2code'
DEBUG = os.path.join(ROOT, 'debug')

TARGETS = [
    ('prime', os.path.join(ROOT, 'bytecode2code', 'prime.pyc'), '_prime_out.py'),
    ('checkerboard', os.path.join(ROOT, 'bytecode2code', 'checkerboard.cpython-39.pyc'), '_cb_out.py'),
    ('py39_syntax_demo', os.path.join(DEBUG, 'py39_syntax_demo.pyc'), '_p39_out.py'),
]

probes = sorted(
    f for f in os.listdir(DEBUG)
    if f.startswith('_probe_') and f.endswith('.pyc')
)
for p in probes:
    TARGETS.append((p[:-4], os.path.join(DEBUG, p), '_probeout_%s.py' % p[7:-4]))

failed = []
for name, pyc, out in TARGETS:
    try:
        src = Decompiler().decompile(PyCParser.parse_file(pyc).code)
    except Exception as exc:  # noqa: BLE001
        print('%-22s DECOMPILE ERROR: %r' % (name, exc))
        failed.append(name)
        continue

    out_path = os.path.join(DEBUG, out)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(src)

    try:
        new = compile(src, out, 'exec')
    except SyntaxError as exc:
        print('%-22s SYNTAX ERROR: %s' % (name, exc))
        failed.append(name)
        continue

    diffs = []
    compare(PyCParser.parse_file(pyc).code, new, '<module>', diffs)
    if diffs:
        print('%-22s DIFFS (%d)' % (name, len(diffs)))
        for d in diffs[:4]:
            print('    ' + d)
        failed.append(name)
    else:
        print('%-22s OK' % name)

print()
print('failed: %d / %d' % (len(failed), len(TARGETS)))
sys.exit(1 if failed else 0)
