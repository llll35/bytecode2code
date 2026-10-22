"""Debug module-level decompile - trace every instruction."""
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

    dec = Decompiler()
    instructions = list(dis.Bytecode(pyc_file.code))
    print("=== Module bytecode ===")
    for i, instr in enumerate(instructions):
        extra = f' arg={instr.arg}' if instr.arg is not None else ''
        print(f"  [{i:2d}] {instr.offset:3d}: {instr.argval or instr.opname}{extra}")
    print()

    # Monkey-patch to trace everything
    orig_process = dec._process_instruction
    def traced_process(instr, instructions, idx, code, stack, stmts, **kwargs):
        opname = instr.opname
        depth_before = len(stack)
        count_before = len(stmts)
        result = orig_process(instr, instructions, idx, code, stack, stmts, **kwargs)
        print(f"  [{idx:2d}] {opname:20s} stack: {depth_before} -> {len(stack)}  stmts: {count_before} -> {len(stmts)}  result={result}")
        return result
    dec._process_instruction = traced_process

    result = dec.decompile(pyc_file.code)
    print(f"\nFinal result:\n{result}")
