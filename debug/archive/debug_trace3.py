import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser
from bytecode2code.disassembler import Disassembler
from bytecode2code.decompiler import Decompiler
import ast

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
d = Disassembler()
instructions = d.disassemble(pyc_file.code)

# Full trace with try/except tracking
exc_stack = []
imported_modules = set()
import_ctx_module = None
stack = []
stmts = []

dec = Decompiler()

i = 0
n = len(instructions)
while i < n:
    # Skip try body instructions
    if exc_stack:
        skip = False
        for block in exc_stack:
            start = block["instr_start"]
            end = block["try_end_idx"]
            if start < i < end:
                skip = True
                break
        if skip:
            print(f"[i={i:2d}] offset={instructions[i].offset:3d} SKIPPED (try body)")
            i += 1
            continue

    instr = instructions[i]
    opname = instr.opname
    print(f"[i={i:2d}] offset={instr.offset:3d} {opname:25s} argval={instr.argval!r}", end="")

    if opname == "SETUP_FINALLY":
        target = int(instr.argval or 0)
        try_end_idx = dec._find_pop_block(instructions, i, target)
        exc_stack.append({"except_target": target, "instr_start": i, "try_end_idx": try_end_idx})
        print(f" -> SETUP_FINALLY push stack={len(exc_stack)} try_end={try_end_idx}")
        i += 1
        continue

    if opname == "POP_BLOCK" and exc_stack and exc_stack[-1]["except_target"] is not None:
        block = exc_stack.pop()
        instr_start = block["instr_start"]
        target = block["except_target"]
        try_end_idx = dec._find_target_idx(instructions, target)
        try_instrs = instructions[instr_start + 1:try_end_idx]
        try_body = dec._emit_statements(pyc_file.code, try_instrs, is_module=True)
        except_instrs = dec._collect_except_handler(instructions, target)
        if except_instrs:
            exc_stmts = dec._emit_statements(pyc_file.code, except_instrs, is_module=True)
            if not exc_stmts:
                exc_stmts = [ast.Pass()]
            exc_type = dec._detect_exception_type(except_instrs)
            handler = ast.ExceptHandler(type=exc_type, name=None, body=exc_stmts)
            stmts.append(ast.Try(try_stmts=try_body, handlers=[handler], orelse=[], finalbody=[]))
        else:
            stmts.append(ast.Try(try_stmts=try_body, handlers=[], orelse=[], finalbody=[]))
        print(f" -> POP_BLOCK: try_body={len(try_body)} exc={len(exc_stmts)}")
        i += 1
        continue

    consumed = dec._process_instruction(instr, instructions, i, pyc_file.code, stack, stmts, is_module=True)
    if consumed == 0:
        i += 1
    else:
        i += consumed

print(f"\nTotal stmts: {len(stmts)}")
for idx, s in enumerate(stmts):
    print(f"  [{idx}] {type(s).__name__}: {ast.dump(s)[:80]}")
