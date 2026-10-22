"""Direct decompiler trace for ALL failing cases on 3.9."""
import ast
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bytecode2code import Decompiler
import dis

CASES = {
    "d2_try_break": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            if x:\n"
        "                break\n"
        "        finally:\n"
        "            x = 0\n"
        "    return x\n"
    ),
    "d2_try_continue": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            if not x:\n"
        "                continue\n"
        "        finally:\n"
        "            x = 1\n"
        "    return x\n"
    ),
    "d3_nested_finally": (
        "def f(x):\n"
        "    try:\n"
        "        try:\n"
        "            try:\n"
        "                return 1\n"
        "            finally:\n"
        "                x = 1\n"
        "        finally:\n"
        "            x = 2\n"
        "    finally:\n"
        "        x = 3\n"
    ),
    "d3_two_levels": (
        "def f(x):\n"
        "    try:\n"
        "        try:\n"
        "            return 1\n"
        "        finally:\n"
        "            x = 1\n"
        "    finally:\n"
        "        x = 2\n"
    ),
    "d3_finally_with_except": (
        "def f(x):\n"
        "    try:\n"
        "        try:\n"
        "            raise ValueError(x)\n"
        "        except ValueError as e:\n"
        "            return e\n"
        "    finally:\n"
        "        x = 1\n"
    ),
    "d4_else_in_loop": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            a = x\n"
        "        except ValueError:\n"
        "            a = 1\n"
        "        else:\n"
        "            a = 2\n"
        "    return a\n"
    ),
    "d4_else_with_break": (
        "def f(xs):\n"
        "    for x in xs:\n"
        "        try:\n"
        "            if x:\n"
        "                break\n"
        "        except ValueError:\n"
        "            pass\n"
        "        else:\n"
        "            x = 1\n"
        "    return x\n"
    ),
}

for name, source in CASES.items():
    print(f"\n{'='*60}")
    print(f"CASE: {name}")
    print(f"{'='*60}")
    co = compile(source, "<test>", "exec")
    f_code = co.co_consts[0]
    print("BYTECODE:")
    dis.dis(f_code)

    instructions = list(dis.get_instructions(f_code))
    for i, inst in enumerate(instructions):
        print(f"  [{i:2d}] offset={inst.offset:4d} {inst.opname:25s} arg={inst.argval}")

    d = Decompiler()
    src = d.decompile(f_code)
    print(f"\nSOURCE:\n{src}")
