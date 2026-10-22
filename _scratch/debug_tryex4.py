"""Debug try_except_return with patched decompiler."""
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

    print("All instructions:")
    for i, instr in enumerate(instructions):
        print(f"  [{i}] offset={instr.offset:3d}  {instr.opname:20s} {instr.argval if instr.argval else ''}")

    # Patch _emit_statements to trace
    orig_emit = dec._emit_statements
    def traced_emit(code, instructions, is_module=False, start=0, end=None, out_stack=None):
        result = orig_emit(code, instructions, is_module=is_module, start=start, end=end, out_stack=out_stack)
        print(f"  _emit_statements(start={start}, end={end}) -> {len(result)} stmts, stack={out_stack}")
        for s in result:
            print(f"    {ast.dump(s)}")
        return result
    dec._emit_statements = traced_emit

    result = dec.decompile(fn_code)
    print(f"\nFinal result:\n{result}")
