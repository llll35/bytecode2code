import dis
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pyvers.decomp_compat import make_decompiler

V = "%d.%d" % sys.version_info[:2]
CASES = {
    "bare_only": (
        "def f(n):\n"
        "    try:\n"
        "        x = int(n)\n"
        "    except:\n"
        "        x = 1\n"
        "    return x\n"
    ),
    "bare_last": (
        "def f(n):\n"
        "    try:\n"
        "        x = int(n)\n"
        "    except TypeError:\n"
        "        x = 0\n"
        "    except:\n"
        "        x = 1\n"
        "    return x\n"
    ),
}

for name, src in CASES.items():
    print("=" * 26, name, "=" * 26)
    print(make_decompiler(V).decompile(compile(src, name + ".py", "exec")))
    print("--- bytecode ---")
    code = compile(src, name + ".py", "exec")
    for const in code.co_consts:
        if hasattr(const, "co_name"):
            dis.dis(const)
