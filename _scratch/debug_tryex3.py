"""Debug: what is try_stack before and after first _emit_statements?"""
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

    dec = Decompiler()
    instructions = list(dis.Bytecode(fn_code))

    # Manual trace
    target = 8
    try_end_idx = dec._find_pop_block(instructions, 0, target)
    handler_start_idx = dec._find_target_idx(instructions, target)
    print(f"try_end_idx={try_end_idx}, handler_start_idx={handler_start_idx}")
    print(f"instructions[try_end_idx]   = {instructions[try_end_idx].opname}")
    print(f"instructions[try_end_idx+1] = {instructions[try_end_idx+1].opname}")
    print(f"instructions[try_end_idx+2] = {instructions[try_end_idx+2].opname}")
    print(f"instructions[try_end_idx+3] = {instructions[try_end_idx+3].opname}")

    # First emit
    try_stack = []
    try_body = dec._emit_statements(
        fn_code, instructions, is_module=False, start=1, end=try_end_idx,
        out_stack=try_stack,
    )
    print(f"\nAfter first emit:")
    print(f"  try_body={try_body}")
    print(f"  try_stack={try_stack}")

    # Check if return value follows POP_BLOCK
    print(f"\n  try_stack truthy? {bool(try_stack)}")
    print(f"  try_body == [Pass()]? {try_body == [ast.Pass()]}")
    print(f"  instr[{try_end_idx+1}].opname = {instructions[try_end_idx+1].opname}")
    print(f"  in LOAD_* set? {instructions[try_end_idx+1].opname in ('LOAD_CONST', 'LOAD_FAST')}")

    # What if we manually compute what _emit_statements would do with extended range?
    extended_try_stack = []
    extended_try_body = dec._emit_statements(
        fn_code, instructions, is_module=False, start=1, end=try_end_idx + 3,
        out_stack=extended_try_stack,
    )
    print(f"\nExtended emit (end={try_end_idx+3}):")
    print(f"  try_body={extended_try_body}")
    print(f"  try_stack={extended_try_stack}")
