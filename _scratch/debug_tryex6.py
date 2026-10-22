"""Debug try_except_return - trace call stacks."""
import ast, dis, os, py_compile, sys, tempfile, traceback

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

    # Patch _process_instruction to trace the try/except path
    orig_process = dec._process_instruction
    call_count = [0]
    def traced_process(instr, instructions, idx, code, stack, stmts, **kwargs):
        opname = instr.opname
        if opname == "POP_BLOCK" and dec._exc_stack:
            call_count[0] += 1
            print(f"\n  === POP_BLOCK handler at idx={idx} (call #{call_count[0]}) ===")
            print(f"    exc_stack={dec._exc_stack}")
            # Print call stack
            for line in traceback.format_stack()[-8:-1]:
                print(f"    {line.rstrip()}")
        return orig_process(instr, instructions, idx, code, stack, stmts, **kwargs)
    dec._process_instruction = traced_process

    # Patch _emit_statements to trace
    orig_emit = dec._emit_statements
    emit_count = [0]
    def traced_emit(code, instructions, is_module=False, start=0, end=None, out_stack=None):
        emit_count[0] += 1
        result = orig_emit(code, instructions, is_module=is_module, start=start, end=end, out_stack=out_stack)
        print(f"  [_emit #{emit_count[0]}] start={start}, end={end} -> {len(result)} stmts, stack={out_stack}")
        return result
    dec._emit_statements = traced_emit

    result = dec.decompile(fn_code)
    print(f"\n\nFinal result:\n{result}")
