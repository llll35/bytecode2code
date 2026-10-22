import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser
from bytecode2code.decompiler import Decompiler, _FuncDefHolder
import ast

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
dec = Decompiler()

# Manually decompile just the class body with tracing
class_code = pyc_file.code.co_consts[7]
instrs = dec.dis.disassemble(class_code)

# Patch _process_instruction to trace
_orig_process = dec._process_instruction

def traced_process(instr, instructions, idx, c, stack, stmts, **kw):
    is_module = kw.get('is_module', False)
    base = kw.get('base_offset', 0)
    handled = any(s <= base + idx < e for s, e in dec._handled_ranges)
    in_exc = any(b['instr_start'] < idx < b['try_end_idx'] for b in dec._exc_stack)
    if not in_exc and not handled:
        print(f'  [{idx:2d}] {instr.opname:25s} arg={str(instr.arg):6s} '
              f'stack={len(stack)} stmts={len(stmts)} '
              f'exc_stack={len(dec._exc_stack)} handled_ranges={dec._handled_ranges}')
    ret = _orig_process(instr, instructions, idx, c, stack, stmts, **kw)
    if not in_exc and not handled:
        print(f'        -> consumed={ret} stack={len(stack)} stmts={len(stmts)}')
    return ret

dec._process_instruction = traced_process

print(f'=== Decompiling class body ({len(instrs)} instrs) ===')
result = dec._emit_statements(class_code, instrs, is_module=False, base_offset=0)
print()
print('=== Final stmts ===')
for i, s in enumerate(result):
    if isinstance(s, ast.FunctionDef):
        print(f'  {i}: FunctionDef {s.name} (body={len(s.body)} stmts)')
    elif isinstance(s, ast.Assign):
        print(f'  {i}: Assign (targets={len(s.targets)})')
    elif isinstance(s, ast.Return):
        print(f'  {i}: Return')
    else:
        print(f'  {i}: {type(s).__name__}')
