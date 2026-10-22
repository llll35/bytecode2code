"""Show how 3.11+ shapes try/finally in the exception table."""
import dis
import sys

VERSION = "%d.%d" % sys.version_info[:2]

CASES = {
    "finally_return": (
        "def f(x):\n"
        "    try:\n"
        "        return 1\n"
        "    finally:\n"
        "        x = 1\n"
    ),
    "finally_raise": (
        "def f(x):\n"
        "    try:\n"
        "        y = 1 / x\n"
        "        return y\n"
        "    finally:\n"
        "        x = 1\n"
    ),
    "finally_pass": (
        "def f(x):\n"
        "    try:\n"
        "        return 1\n"
        "    finally:\n"
        "        pass\n"
    ),
    "finally_stmt": (
        "def f(x):\n"
        "    try:\n"
        "        y = x\n"
        "    finally:\n"
        "        x = 1\n"
    ),
    "except_basic": (
        "def f(x):\n"
        "    try:\n"
        "        y = x\n"
        "    except ValueError:\n"
        "        y = 1\n"
    ),
    "except_else": (
        "def f(x):\n"
        "    try:\n"
        "        y = x\n"
        "    except ValueError:\n"
        "        y = 1\n"
        "    else:\n"
        "        y = 2\n"
    ),
    "except_as": (
        "def f(x):\n"
        "    try:\n"
        "        y = x\n"
        "    except ValueError as e:\n"
        "        y = 1\n"
    ),
    "nested_return": (
        "def f(x):\n"
        "    try:\n"
        "        try:\n"
        "            return 1\n"
        "        finally:\n"
        "            x = 1\n"
        "    finally:\n"
        "        x = 2\n"
    ),
}

for name, src in CASES.items():
    print("=" * 66)
    print("%s  (Python %s)" % (name, VERSION))
    print("=" * 66)
    print(src)
    code = compile(src, name + ".py", "exec")
    for const in code.co_consts:
        if hasattr(const, "co_name") and const.co_name == "f":
            dis.dis(const)
    print()
