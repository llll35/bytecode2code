import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser
from bytecode2code.disassembler import Disassembler, Instruction
from bytecode2code.decompiler import Decompiler, ASTNode
import ast
from typing import List, Dict, Any

class DebugDecompiler(Decompiler):
    def _process_instruction(self, instr, instructions, idx, code, stack, stmts, is_module=False):
        opname = instr.opname
        if opname in ("SETUP_FINALLY", "SETUP_EXCEPT", "SETUP_WITH"):
            target = int(instr.argval if instr.argval is not None else (instr.arg or 0))
            self._exc_stack.append({
                "except_target": target,
                "instr_start": idx,
            })
            print(f"[DEBUG] SETUP_FINALLY at idx={idx} offset={instr.offset}, target={target}, stack_size={len(self._exc_stack)}")
            return 1
        if opname == "POP_BLOCK" and self._exc_stack and self._exc_stack[-1]["except_target"] is not None:
            block = self._exc_stack.pop()
            instr_start = block["instr_start"]
            target = block["except_target"]
            try_end_idx = self._find_target_idx(instructions, target)
            print(f"[DEBUG] POP_BLOCK at idx={idx}, instr_start={instr_start}, target={target}, try_end_idx={try_end_idx}")
            print(f"[DEBUG]   total instructions: {len(instructions)}, try_instrs: {instr_start+1} to {try_end_idx} = {try_end_idx - instr_start - 1} instrs")
            try_instrs = instructions[instr_start + 1:try_end_idx]
            print(f"[DEBUG]   try_instrs offsets: {[t.offset for t in try_instrs]}")
            try_body = self._emit_statements(code, try_instrs, is_module=is_module)
            print(f"[DEBUG]   try_body stmt count: {len(try_body)}")
            except_instrs = self._collect_except_handler(instructions, target)
            print(f"[DEBUG]   except_instrs count: {len(except_instrs)}, offsets: {[t.offset for t in except_instrs]}")
            if except_instrs:
                exc_stmts = self._emit_statements(code, except_instrs, is_module=is_module)
                if not exc_stmts:
                    exc_stmts = [ast.Pass()]
                exc_type = self._detect_exception_type(except_instrs)
                handler = ast.ExceptHandler(type=exc_type, name=None, body=exc_stmts)
                stmts.append(ast.Try(try_stmts=try_body, handlers=[handler], orelse=[], finalbody=[]))
            else:
                stmts.append(ast.Try(try_stmts=try_body, handlers=[], orelse=[], finalbody=[]))
            return 1
        return super()._process_instruction(instr, instructions, idx, code, stack, stmts, is_module)

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
d = Disassembler()
instructions = d.disassemble(pyc_file.code)
print(f"Total instructions: {len(instructions)}")
dec = DebugDecompiler()
src = dec.decompile(pyc_file.code)
print("\n=== OUTPUT ===")
print(src[:800])
