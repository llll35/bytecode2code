"""Temporary: trace module instruction loop (fixed signature)."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pyvers import interp  # noqa: E402

SRC = "async def f(p):\n    return [x async for x in p]\n"

RUNNER = r'''
import sys, os, traceback
root = sys.argv[1]
sys.path.insert(0, os.path.join(root, "pyvers"))
sys.path.insert(0, root)
sys.path.insert(0, os.path.join(root, "embed_python"))
sys.path.insert(0, os.path.join(root, "embed_python", "python-" + sys.argv[2]))
import decomp_compat
import bytecode2code.decompiler as dc

orig_pi = dc.Decompiler._process_instruction
def traced_pi(self, instr, instructions, idx, code, stack, stmts,
               is_module=False, limit=None):
    try:
        n = orig_pi(self, instr, instructions, idx, code, stack, stmts,
                    is_module, limit)
        print("  PI %-26s -> %s | stack=%s stmts=%s" % (
            instr.opname, n, [type(s).__name__ for s in stack],
            [type(s).__name__ for s in stmts]))
        return n
    except Exception:
        traceback.print_exc()
        raise
dc.Decompiler._process_instruction = traced_pi

orig_mf = dc.Decompiler._process_make_function
def traced_mf(self, instr, stack, stmts, code):
    r = orig_mf(self, instr, stack, stmts, code)
    print("  MAKE_FUNCTION arg=%s stack=%s stmts=%s" % (
        instr.arg, [type(s).__name__ for s in stack],
        [type(s).__name__ for s in stmts]))
    return r
dc.Decompiler._process_make_function = traced_mf

src = sys.argv[3]
code = compile(src, "<x>", "exec")
cls = decomp_compat.decompiler_for(sys.argv[2])
print("RESULT", repr(cls().decompile(code)))
'''


def main():
    for version in ("3.9", "3.10"):
        folder = tempfile.mkdtemp(prefix="b9_")
        runner = os.path.join(folder, "r.py")
        with open(runner, "w", encoding="utf-8") as f:
            f.write(RUNNER)
        proc = subprocess.run(
            [interp.interpreter_path(version), runner, HERE, version, SRC],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        print("=== %s" % version)
        print(proc.stdout.decode("utf-8", "replace"))


if __name__ == "__main__":
    main()