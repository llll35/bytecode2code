"""Debug: trace decompiler on ret_simple case."""
import ast, dis, os, py_compile, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser


SRC = "def a():\n    try:\n        return 1\n    finally:\n        x = 1\n"

with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "test.py")
    pyc_path = os.path.join(tmp, "test.pyc")
    with open(src_path, "w") as f:
        f.write(SRC)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)

    pyc_file = PyCParser.parse_file(pyc_path)
    fn_code = next(co for co in pyc_file.code.co_consts
                   if hasattr(co, "co_name") and co.co_name == "a")

    instructions = list(dis.Bytecode(fn_code))
    print("=== Bytecode ===")
    for i, instr in enumerate(instructions):
        extra = f' arg={instr.arg}' if instr.arg is not None else ''
        print(f"  [{i:2d}] {instr.offset:3d}: {instr.argval or instr.opname}{extra}")

    print()

    dec = Decompiler()

    # Trace _process_instruction
    orig_process = dec._process_instruction
    def traced_process(instr, instructions, idx, code, stack, stmts, **kwargs):
        opname = instr.opname
        # Show call stack to understand context
        if opname in ("RETURN_VALUE", "POP_BLOCK", "PUSH_EXC_INFO", "RERAISE"):
            print(f"[process] idx={idx} op={opname} stack_depth={len(stack)} stmts_count={len(stmts)}")
        return orig_process(instr, instructions, idx, code, stack, stmts, **kwargs)
    dec._process_instruction = traced_process

    # Trace _emit_statements
    orig_emit = dec._emit_statements
    emit_count = [0]
    def traced_emit(code, instructions, is_module=False, start=0, end=None, out_stack=None):
        n = len(instructions) if end is None else end
        ops = [instructions[j].opname for j in range(start, n)]
        print(f"[emit #{emit_count[0]}] start={start}, end={n}, range=[{', '.join(ops)}]")
        result = orig_emit(code, instructions, is_module=is_module, start=start, end=end, out_stack=out_stack)
        emit_count[0] += 1
        print(f"  -> {len(result)} stmts, stack={out_stack if out_stack is not None else 'N/A'}")
        for s in result:
            print(f"     {ast.dump(s)}")
        return result
    dec._emit_statements = traced_emit

    result = dec.decompile(fn_code)
    print(f"\nFinal result:\n{result}")
