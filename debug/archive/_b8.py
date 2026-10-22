"""Temporary: trace module instruction loop."""
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

orig = dc.Decompiler._emit_statements
def traced(self, code, instructions, is_module=False, start=0, end=None,
           out_stack=None):
    print("EMIT_STMT module=%s start=%s end=%s" % (is_module, start, end))
    try:
        out = orig(self, code, instructions, is_module, start, end, out_stack)
        print("  ->", [type(s).__name__ for s in out])
        return out
    except Exception:
        traceback.print_exc()
        raise
dc.Decompiler._emit_statements = traced

orig_pi = dc.Decompiler._process_instruction
def traced_pi(self, instr, instructions, idx, code, stack, stmts, is_module=False):
    try:
        n = orig_pi(self, instr, instructions, idx, code, stack, stmts, is_module)
        print("  PI %-26s -> %s | stack=%s stmts=%s" % (
            instr.opname, n, [type(s).__name__ for s in stack],
            [type(s).__name__ for s in stmts]))
        return n
    except Exception:
        traceback.print_exc()
        raise
dc.Decompiler._process_instruction = traced_pi

src = sys.argv[3]
code = compile(src, "<x>", "exec")
cls = decomp_compat.decompiler_for(sys.argv[2])
print("RESULT", repr(cls().decompile(code)))
'''


def main():
    for version in ("3.9", "3.10"):
        folder = tempfile.mkdtemp(prefix="b8_")
        runner = os.path.join(folder, "r.py")
        with open(runner, "w", encoding="utf-8") as f:
            f.write(RUNNER)
        proc = subprocess.run(
            [interp.interpreter_path(version), runner, HERE, version, SRC],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        print("=== %s" % version)
        print(proc.stdout.decode("utf-8", "replace")[:6000])


if __name__ == "__main__":
    main()