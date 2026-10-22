import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pyvers.decomp_compat import make_decompiler

V = "%d.%d" % sys.version_info[:2]
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
    "as_else": (
        "def f(n):\n"
        "    try:\n"
        "        x = int(n)\n"
        "    except ValueError as e:\n"
        "        print(e)\n"
        "    else:\n"
        "        return x\n"
    ),
    "as_no_else": (
        "def f(n):\n"
        "    try:\n"
        "        x = int(n)\n"
        "    except ValueError as e:\n"
        "        print(e)\n"
        "    return None\n"
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
    print("=" * 30, name, "=" * 30)
    print(make_decompiler(V).decompile(compile(src, name + ".py", "exec")))
