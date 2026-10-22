import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser, collect_code_objects
from bytecode2code.decompiler import Decompiler, ASTNode
from bytecode2code.disassembler import Instruction
import ast

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
dec = Decompiler()

objects = collect_code_objects(pyc_file.code)

# Find _get_non_repeating_part
for depth, obj in objects:
    if getattr(obj, 'co_name', '') == '_get_non_repeating_part':
        code = obj
        break

instrs = dec.dis.disassemble(code)

# Patch _process_instruction to trace stack
_orig_process = dec._process_instruction
def traced_process(instr, instructions, idx, c, stack, stmts, **kw):
    ret = _orig_process(instr, instructions, idx, c, stack, stmts, **kw)
    print(f"[{idx:3d}] {instr.opname:25s} -> stack={len(stack)} stmts={len(stmts)}")
    if stack:
        top = stack[-1]
        try:
            top_str = ast.unparse(top)
        except:
            top_str = ast.dump(top)
        print(f"       top of stack: {top_str[:80]}")
    return ret

dec._process_instruction = traced_process
stmts = dec._emit_statements(code, instrs)
