import sys, dis
sys.path.insert(0, r'D:\py\bytecode2code')
from bytecode2code.pyc_parser import PyCParser

code = PyCParser.parse_file(r'D:\py\bytecode2code\debug\py39_syntax_demo.pyc').code
ins = list(dis.get_instructions(code))
mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
if mode == 'all':
    lo, hi = 0, len(ins)
else:
    lo, hi = int(sys.argv[2]), int(sys.argv[3])
for k in range(lo, min(hi, len(ins))):
    i = ins[k]
    print('%4d %5d %-26s %s' % (k, i.offset, i.opname, i.argrepr))
