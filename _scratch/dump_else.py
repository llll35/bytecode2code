import dis
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CASES = {
    "no_as_else": (
        "def f(n):\n"
        "    try:\n"
        "        x = int(n)\n"
        "    except ValueError:\n"
        "        print(n)\n"
        "    else:\n"
        "        return x\n"
    ),
    "as_else_stmt": (
        "def f(n):\n"
        "    try:\n"
        "        x = int(n)\n"
        "    except ValueError as e:\n"
        "        print(e)\n"
        "    else:\n"
        "        x = 2\n"
        "    return x\n"
    ),
}

for name, src in CASES.items():
    print("=" * 26, name, "=" * 26)
    code = compile(src, name + ".py", "exec")
    for const in code.co_consts:
        if hasattr(const, "co_name"):
            dis.dis(const)
