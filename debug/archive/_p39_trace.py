import sys, ast, dis

sys.path.insert(0, r'D:\py\bytecode2code')

from bytecode2code import decompiler as D
from bytecode2code.pyc_parser import PyCParser

_orig_call = D.Decompiler._process_call
_depth = [0]


def _label(it):
    if isinstance(it, D._FuncDefHolder):
        return 'HOLDER(%s)' % it.func_def.name
    if isinstance(it, D._CompMaker):
        return 'COMPMAKER(%s)' % it.code_obj.co_name
    if isinstance(it, ast.Constant):
        return 'Const(%r)' % (it.value,)
    if isinstance(it, ast.Name):
        return 'Name(%s)' % it.id
    if isinstance(it, ast.Call):
        return 'Call(%s)' % ast.dump(it.func)[:40]
    if isinstance(it, ast.Dict):
        return 'Dict(%d)' % len(it.keys)
    return type(it).__name__


def traced(self, opname, instr, stack, stmts):
    if opname in ('CALL_FUNCTION', 'MAKE_FUNCTION') and 440 <= instr.offset <= 470:
        print('%s%5d %-18s arg=%s stack=%s' % (
            '  ' * _depth[0], instr.offset, opname, instr.arg,
            [_label(x) for x in stack]))
    _depth[0] += 1
    try:
        return _orig_call(self, opname, instr, stack, stmts)
    finally:
        _depth[0] -= 1


D.Decompiler._process_call = traced

code = PyCParser.parse_file(
    r'D:\py\bytecode2code\debug\py39_syntax_demo.pyc'
).code
d = D.Decompiler()
src = d.decompile(code)
print('--- ok, %d chars' % len(src))
