import sys
sys.setrecursionlimit(3000)
from bytecode2code.decompiler import Decompiler, _FuncDefHolder
from bytecode2code.pyc_parser import PyCParser
code = PyCParser.parse_file('_probe_nonlocal.pyc').code
d = Decompiler()

orig_process = d._process_instruction
def traced_process(instr, instructions, idx, code, stack, stmts, **kw):
    pre_len = len(stack)
    result = orig_process(instr, instructions, idx, code, stack, stmts, **kw)
    post_len = len(stack)
    if instr.opname in ('LOAD_FAST', 'STORE_DEREF', 'LOAD_CLOSURE', 'BUILD_TUPLE',
                        'LOAD_CONST', 'MAKE_FUNCTION', 'STORE_FAST'):
        detail = ''
        if instr.opname == 'LOAD_CONST' and hasattr(instr.argval, 'co_code'):
            detail = ' [code=%s]' % instr.argval.co_name
        print('  [%s %r] pre=%d post=%d stmts=%d%s' % (
            instr.opname, instr.argval, pre_len, post_len, len(stmts), detail))
    return result

d._process_instruction = traced_process
result = d.decompile(code)
print('=== OUTPUT ===')
print(result)
