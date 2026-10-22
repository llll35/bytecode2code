"""Minimal debug: trace try_stack and condition for ret_break."""
import ast, dis, os, py_compile, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bytecode2code.pyc_parser import PyCParser
from bytecode2code.decompiler import Decompiler

SOURCE = "def f(xs):\n    for x in xs:\n        try:\n            return x\n        finally:\n            pass\n    return 0\n"

with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "test.py")
    pyc_path = os.path.join(tmp, "test.pyc")
    with open(src_path, "w") as f: f.write(SOURCE)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)

    pyc_file = PyCParser.parse_file(pyc_path)
    fn_code = next(co for co in pyc_file.code.co_consts
                   if hasattr(co, "co_name") and co.co_name == "f")

    print("=== Bytecode ===")
    dis.dis(fn_code)

    dec = Decompiler()
    orig = dec._process_instruction

    def traced(self, opname, instr, instructions, idx, code, stack, stmts, **kwargs):
        if opname == "SETUP_FINALLY":
            target = int(instr.argval or instr.arg or 0)
            try_end_idx = dec._find_pop_block(instructions, idx, target)
            dec._exc_stack.append({
                "except_target": target,
                "instr_start": idx,
                "try_end_idx": try_end_idx,
            })
            print(f"\n[SETUP_FINALLY] idx={idx}, try_end_idx={try_end_idx}")
            print(f"  instr[{try_end_idx}]  = {instructions[try_end_idx].opname}")
            if try_end_idx + 1 < len(instructions):
                print(f"  instr[{try_end_idx+1}] = {instructions[try_end_idx+1].opname}")
            return 1

        if opname == "POP_BLOCK" and dec._exc_stack and dec._exc_stack[-1]["except_target"] is not None:
            block = dec._exc_stack.pop()
            instr_start = block["instr_start"]
            target = block["except_target"]
            handler_start_idx = dec._find_target_idx(instructions, target)
            try_end_idx = block["try_end_idx"]
            if try_end_idx <= instr_start or try_end_idx > handler_start_idx:
                try_end_idx = dec._find_pop_block(instructions, instr_start, target)

            try_stack = []
            try_body = dec._emit_statements(
                code, instructions, is_module=False, start=instr_start + 1,
                end=try_end_idx, out_stack=try_stack,
            )
            print(f"\n[POP_BLOCK handler] try_end_idx={try_end_idx}")
            print(f"  try_body = {[ast.dump(s) for s in try_body]}")
            print(f"  try_stack = {try_stack}")
            print(f"  instr[{try_end_idx}].opname = {instructions[try_end_idx].opname}")
            if try_end_idx + 1 < len(instructions):
                print(f"  instr[{try_end_idx+1}].opname = {instructions[try_end_idx+1].opname}")

            cond = (
                bool(try_stack)
                and instructions[try_end_idx].opname == "POP_BLOCK"
                and try_end_idx + 1 < len(instructions)
                and instructions[try_end_idx + 1].opname == "RETURN_VALUE"
            )
            print(f"  FIX CONDITION = {cond}")
            if cond:
                print(f"  -> Would pop {try_stack[-1]} and append Return")
            else:
                if not bool(try_stack):
                    print(f"  -> try_stack is EMPTY (main issue)")
                if not instructions[try_end_idx].opname == "POP_BLOCK":
                    print(f"  -> instr[{try_end_idx}] is NOT POP_BLOCK")
                if not instructions[try_end_idx + 1].opname == "RETURN_VALUE":
                    nxt = instructions[try_end_idx + 1].opname if try_end_idx + 1 < len(instructions) else "N/A"
                    print(f"  -> instr[{try_end_idx+1}] is NOT RETURN_VALUE (it's {nxt})")

        return orig(opname, instr, instructions, idx, code, stack, stmts)

    dec._process_instruction = lambda *a, **k: traced(dec, *a, **k)

    result = dec.decompile(pyc_file.code)
    print(f"\n=== Output ===\n{result}")

    # Check semantic equivalence
    g_orig, g_decomp = {}, {}
    exec(compile(SOURCE, "orig.py", "exec"), g_orig)
    exec(compile(result, "decomp.py", "exec"), g_decomp)
    for xs in ([1,2,3], [], [42]):
        r1 = g_orig["f"](xs)
        r2 = g_decomp["f"](xs)
        print(f"f({xs}): orig={r1}, decomp={r2}, match={r1==r2}")
