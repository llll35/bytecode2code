"""Debug why the fix at lines 2046-2052 doesn't trigger for ret_break."""

import ast
import dis
import os
import py_compile
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bytecode2code.pyc_parser import PyCParser
from bytecode2code.decompiler import Decompiler


SOURCE = """\
def f(xs):
    for x in xs:
        try:
            return x
        finally:
            pass
    return 0
"""

with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "test.py")
    pyc_path = os.path.join(tmp, "test.pyc")
    with open(src_path, "w", encoding="utf-8") as f:
        f.write(SOURCE)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)

    pyc_file = PyCParser.parse_file(pyc_path)

    # Find function f code object
    fn_code = None
    for co in pyc_file.code.co_consts:
        if hasattr(co, "co_name") and co.co_name == "f":
            fn_code = co
            break

    print("=== Bytecode for f() ===")
    dis.dis(fn_code)

    print("\n=== Manual instruction listing ===")
    code = fn_code
    ops = code.co_code
    i = 0
    idx = 0
    instrs = []
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
            argval = dis.opdata[op][2](code, arg)
        instrs.append((idx, offset, name, arg, argval))
        idx += 1
    for i, (idx, offset, name, arg, argval) in enumerate(instrs):
        marker = ">>" if any(t == offset for _, t, _, _, _ in instrs if False) else "  "
        print(f"  {idx:3d}  {offset:4d}  {name:20s}  arg={arg!r}  argval={argval!r}")

    # Find SETUP_FINALLY
    print("\n=== SETUP_FINALLY analysis ===")
    for i, (idx, offset, name, arg, argval) in enumerate(instrs):
        if name == "SETUP_FINALLY":
            target_offset = arg
            print(f"  SETUP_FINALLY at idx={idx}, offset={offset}, target_offset={target_offset}")
            # Find POP_BLOCK
            depth = 1
            try_end_idx = None
            for j in range(idx + 1, len(instrs)):
                _, off, op, _, _ = instrs[j]
                if op in ("SETUP_FINALLY", "SETUP_EXCEPT", "SETUP_WITH", "SETUP_ASYNC_WITH", "SETUP_LOOP"):
                    depth += 1
                elif op == "POP_BLOCK":
                    if depth <= 1:
                        try_end_idx = j
                        depth = 1  # keep at 1 per the docstring
                    else:
                        depth -= 1
            print(f"  try_end_idx (POP_BLOCK) = {try_end_idx}")
            if try_end_idx is not None:
                _, _, op1, _, _ = instrs[try_end_idx]
                _, _, op2, _, _ = instrs[try_end_idx + 1] if try_end_idx + 1 < len(instrs) else (None, None, None, None, None)
                print(f"  instructions[try_end_idx]   = {op1}")
                print(f"  instructions[try_end_idx+1] = {op2}")

    # Check try_stack by instrumenting the decompiler
    print("\n=== Running Decompiler with instrumentation ===")
    dec = Decompiler()

    orig_handle_finally = dec._process_stmt

    def traced_handle_finally(self, opname, instr, instructions, idx, code, stack, stmts):
        from bytecode2code.decompiler import List
        if opname != "SETUP_FINALLY":
            return orig_handle_finally(opname, instr, instructions, idx, code, stack, stmts)

        target = self._jump_target(instr)
        try_end_idx = self._find_pop_block(instructions, idx, target)
        print(f"  SETUP_FINALLY: try_end_idx={try_end_idx}")
        if try_end_idx + 1 < len(instructions):
            print(f"    instr[try_end_idx]   = {instructions[try_end_idx].opname}")
            print(f"    instr[try_end_idx+1] = {instructions[try_end_idx+1].opname}")

        # Call parent but intercept try_stack
        # We need to trace _emit_statements to see what try_stack contains
        try_stack = []
        try_body = self._emit_statements(
            code, instructions, is_module=False, start=idx + 1, end=try_end_idx,
            out_stack=try_stack,
        )
        print(f"  try_body = {[ast.dump(s) for s in try_body]}")
        print(f"  try_stack after emit = {try_stack}")
        print(f"  Condition check:")
        print(f"    try_stack bool = {bool(try_stack)}")
        if try_end_idx < len(instructions):
            print(f"    instr[{try_end_idx}].opname == 'POP_BLOCK' = {instructions[try_end_idx].opname == 'POP_BLOCK'}")
        if try_end_idx + 1 < len(instructions):
            print(f"    instr[{try_end_idx+1}].opname == 'RETURN_VALUE' = {instructions[try_end_idx+1].opname == 'RETURN_VALUE'}")

        # Now call the real handler
        return orig_handle_finally(opname, instr, instructions, idx, code, stack, stmts)

    dec._process_stmt = lambda *a, **k: traced_handle_finally(dec, *a, **k)

    result = dec.decompile(pyc_file.code)
    print(f"\n=== Final output ===")
    print(result)
