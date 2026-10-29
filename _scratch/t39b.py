import dis
import sys
sys.path.insert(0, '.')
from tests.cases import FLOW_PROBES
name = sys.argv[1] if len(sys.argv) > 1 else 'finally_return'
source = FLOW_PROBES[name]
print(source)
code = compile(source, 't', 'exec')
f = [c for c in code.co_consts if getattr(c, 'co_name', '') == 'f'][0]
for i, ins in enumerate(dis.get_instructions(f)):
    print("%3d %5d %-28s %s" % (i, ins.offset, ins.opname, ins.argrepr))
