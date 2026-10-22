import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bytecode2code.decompiler import Decompiler
from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser
from tests.equivalence import compare

CASES = {
    "as_else": "def f(n):\n    try:\n        x = int(n)\n    except ValueError as e:\n        print(e)\n    else:\n        return x\n    return None\n",
    "as_noreturn": "def f(n):\n    try:\n        x = int(n)\n    except ValueError as e:\n        print(e)\n    return None\n",
    "as_then_return": "def f(n):\n    try:\n        x = int(n)\n    except ValueError as e:\n        print(e)\n    return x\n",
    "as_ret_in_handler": "def f(n):\n    try:\n        x = int(n)\n    except ValueError as e:\n        return 1\n    return None\n",
    "as_else_ret": "def f(n):\n    try:\n        x = int(n)\n    except ValueError as e:\n        print(e)\n    else:\n        return x\n",
    "three": (
        "def f(n):\n"
        "    try:\n"
        "        x = int(n)\n"
        "    except ValueError as e:\n"
        "        print(e)\n"
        "    except TypeError:\n"
        "        raise\n"
        "    except:\n"
        "        raise ValueError('bad')\n"
        "    else:\n"
        "        return x\n"
        "    return None\n"
    ),
    "three_noelse": (
        "def f(n):\n"
        "    try:\n"
        "        x = int(n)\n"
        "    except ValueError as e:\n"
        "        print(e)\n"
        "    except TypeError:\n"
        "        raise\n"
        "    except:\n"
        "        raise ValueError('bad')\n"
        "    return None\n"
    ),
    "raise_bare_handler": "def f(n):\n    try:\n        x = int(n)\n    except TypeError:\n        raise\n    return None\n",
}
tmp = tempfile.mkdtemp()
for name, src in CASES.items():
    p = os.path.join(tmp, name + ".pyc")
    compile_source_to_pyc(src, p)
    original = PyCParser.parse_file(p).code
    out = Decompiler().decompile(original)
    try:
        d = compare(original, compile(out, name + ".py", "exec"))
    except SyntaxError as exc:
        print("=== %-18s SyntaxError %s" % (name, exc))
        continue
    print("=== %-18s %s" % (name, "identical" if not d else "DIFF: " + "; ".join(d[:1])))
    if d:
        print("   " + out.replace("\n", "\n   "))