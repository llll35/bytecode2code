"""Debug try/except + return specifically."""
import ast, dis, os, py_compile, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser


SRC = (
    "def n():\n"
    "    try:\n"
    "        return 5\n"
    "    except ValueError:\n"
    "        return 6\n"
)

with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "n.py")
    pyc_path = os.path.join(tmp, "n.pyc")
    with open(src_path, "w") as f: f.write(SRC)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)

    pyc_file = PyCParser.parse_file(pyc_path)
    fn_code = next(co for co in pyc_file.code.co_consts
                   if hasattr(co, "co_name") and co.co_name == "n")

    print("=== Bytecode ===")
    dis.dis(fn_code)

    dec = Decompiler()

    # Trace _process_instruction
    orig = dec._process_instruction

    def traced(self, opname, instr, instructions, idx, code, stack, stmts, **kwargs):
        if opname == "SETUP_FINALLY":
            target = int(instr.argval or instr.arg or 0)
            try_end_idx = self._find_pop_block(instructions, idx, target)
            self._exc_stack.append({
                "except_target": target,
                "instr_start": idx,
                "try_end_idx": try_end_idx,
            })
            print(f"\n[SETUP_FINALLY] idx={idx}, target={target}, try_end_idx={try_end_idx}")
            for i, ins in enumerate(instructions):
                marker = ">>" if ins.is_jump_target else "  "
                print(f"  {marker} {i:3d} {ins.offset:4d} {ins.opname:20s} arg={ins.arg}")
            return 1

        if opname == "POP_BLOCK" and self._exc_stack and self._exc_stack[-1]["except_target"] is not None:
            block = self._exc_stack.pop()
            instr_start = block["instr_start"]
            target = block["except_target"]
            handler_start_idx = self._find_target_idx(instructions, target)
            try_end_idx = block["try_end_idx"]
            print(f"\n[POP_BLOCK] instr_start={instr_start}, try_end_idx={try_end_idx}, handler_start_idx={handler_start_idx}")
            print(f"  instructions[{try_end_idx}]   = {instructions[try_end_idx].opname}")
            print(f"  instructions[{try_end_idx+1}] = {instructions[try_end_idx+1].opname if try_end_idx+1 < len(instructions) else 'N/A'}")
            print(f"  instructions[{try_end_idx+2}] = {instructions[try_end_idx+2].opname if try_end_idx+2 < len(instructions) else 'N/A'}")
            print(f"  instructions[{try_end_idx+3}] = {instructions[try_end_idx+3].opname if try_end_idx+3 < len(instructions) else 'N/A'}")

        return orig(opname, instr, instructions, idx, code, stack, stmts, **kwargs)

    dec._process_instruction = lambda *a, **k: traced(dec, *a, **k)

    result = dec.decompile(pyc_file.code)
    print(f"\n=== Output ===\n{result}")
