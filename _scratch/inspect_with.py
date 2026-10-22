"""Inspect handler ranges and pop-block choices for with cases."""
import os
import sys
import py_compile
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bytecode2code.decompiler import Decompiler
from bytecode2code.pyc_parser import PyCParser

CASES = {
    "multi_body": "def f(a, b):\n    with a as x, b as y:\n        z = x + y\n    return z\n",
    "multi_return": "def f(a, b):\n    with a as x, b as y:\n        return x + y\n",
    "three_return": "def f(a, b, c):\n    with a as x, b as y, c as z:\n        return x\n",
    "if_return": (
        "def f(a, c):\n"
        "    with a as x:\n"
        "        if c:\n"
        "            return x\n"
        "        y = 1\n"
        "    return y\n"
    ),
    "with_try": (
        "def f(a, p):\n"
        "    with a as x:\n"
        "        try:\n"
        "            g(x)\n"
        "        except ValueError:\n"
        "            pass\n"
        "        h(x)\n"
        "    return x\n"
    ),
}

tmp = tempfile.mkdtemp()
for name, src in CASES.items():
    p = os.path.join(tmp, name + ".py")
    c = os.path.join(tmp, name + ".pyc")
    with open(p, "w") as f:
        f.write(src)
    py_compile.compile(p, cfile=c, doraise=True)
    code = PyCParser.parse_file(c).code
    d = Decompiler()
    fn = next(x for x in code.co_consts if hasattr(x, "co_code"))
    ins = d.dis.disassemble(fn)
    print("=" * 50)
    print(name)
    print("ranges:", [(s, e, ins[s].offset, ins[e].offset) for s, e in d._with_handler_ranges(ins)])
    orig = d._find_pop_block
    calls = []

    def tp(instructions, setup_idx, target, _o=orig):
        r = _o(instructions, setup_idx, target)
        calls.append((setup_idx, target, r, instructions[r].offset))
        return r

    d._find_pop_block = tp
    out = d.decompile(code)
    for s, t, r, off in calls:
        print("  pop setup=%d off=%d target=%d -> idx %d off=%d" % (
            s, ins[s].offset, t, r, off))
    print("-- out --")
    print(out)
