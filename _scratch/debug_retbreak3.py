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

    # Instead of monkey-patching, just call _emit_statements directly on the
    # relevant range to inspect try_stack
    instructions = list(dis.Bytecode(fn_code)) if hasattr(dis, "Bytecode") else []
    # Fallback: manual parse
    ops = fn_code.co_code
    instructions = []
    i = 0
    while i < len(ops):
        offset = i
        op = ops[i]
        i += 1
        name = dis.opname[op]
        arg = None
        argval = None
        if op >= dis.HAVE_ARGUMENT:
            arg = ops[i] | (ops[i+1] << 8)
            i += 2
            try:
                argval = dis._unpack_const(fn_code, arg)
            except Exception:
                try:
                    argval = dis.opdata[op][2](fn_code, arg)
                except Exception:
                    pass
        instructions.append(type('Instr', (), {
            'offset': offset, 'opname': name, 'arg': arg,
            'argval': argval, 'is_jump_target': False
        })())

    # Mark jump targets
    for ins in instructions:
        if ins.argval is not None and isinstance(ins.argval, int):
            for j in instructions:
                if j.offset == ins.argval:
                    j.is_jump_target = True

    # Find SETUP_FINALLY
    setup_idx = None
    for i, ins in enumerate(instructions):
        if ins.opname == "SETUP_FINALLY":
            setup_idx = i
            break

    print(f"\n=== SETUP_FINALLY at idx={setup_idx} ===")
    if setup_idx is not None:
        target_offset = instructions[setup_idx].arg
        # Find try_end_idx via _find_pop_block logic
        dec = Decompiler()
        try_end_idx = dec._find_pop_block(instructions, setup_idx, target_offset)
        print(f"  target_offset={target_offset}, try_end_idx={try_end_idx}")
        print(f"  instr[{try_end_idx}]   = {instructions[try_end_idx].opname}")
        print(f"  instr[{try_end_idx+1}] = {instructions[try_end_idx+1].opname if try_end_idx+1 < len(instructions) else 'N/A'}")

        # Call _emit_statements with a fresh decompiler to see try_stack
        dec2 = Decompiler()
        try_stack = []
        try_body = dec2._emit_statements(
            fn_code, instructions, is_module=False, start=setup_idx + 1,
            end=try_end_idx, out_stack=try_stack,
        )
        print(f"\n  try_body = {[ast.dump(s) for s in try_body]}")
        print(f"  try_stack = {try_stack}")

        cond = (
            bool(try_stack)
            and instructions[try_end_idx].opname == "POP_BLOCK"
            and try_end_idx + 1 < len(instructions)
            and instructions[try_end_idx + 1].opname == "RETURN_VALUE"
        )
        print(f"\n  FIX CONDITION = {cond}")
        if not cond:
            if not bool(try_stack):
                print("  -> try_stack is EMPTY")
            if not instructions[try_end_idx].opname == "POP_BLOCK":
                print(f"  -> instr[{try_end_idx}] is NOT POP_BLOCK (it's {instructions[try_end_idx].opname})")
            if try_end_idx + 1 < len(instructions):
                nxt = instructions[try_end_idx + 1].opname
                if nxt != "RETURN_VALUE":
                    print(f"  -> instr[{try_end_idx+1}] is '{nxt}', not RETURN_VALUE")

    # Also run full decompile
    print("\n=== Full decompile ===")
    dec3 = Decompiler()
    result = dec3.decompile(pyc_file.code)
    print(result)

    # Semantic check
    g_orig, g_decomp = {}, {}
    exec(compile(SOURCE, "orig.py", "exec"), g_orig)
    exec(compile(result, "decomp.py", "exec"), g_decomp)
    for xs in ([1,2,3], [], [42]):
        r1 = g_orig["f"](xs)
        r2 = g_decomp["f"](xs)
        print(f"f({xs}): orig={r1}, decomp={r2}, match={r1==r2}")
