import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyvers import compile_source, disassemble
CASES = {
 "else_in_loop": (
  "def f(xs):\n"
  "    for x in xs:/n"
  "        try:/n"
  "            a = x\n"
  "        except ValueError:/n"
  "            a = 1\n"
  "        else:/n"
  "            a = 2\n"
  "    return a\n"),
 "else_with_break": (
  "def f(xs):\n"
  "    for x in xs:/n"
  "        try:/n"
  "            if x:/n"
  "                break\n"
  "        except ValueError:/n"
  "            pass\n"
  "        else:/n"
  "            x = 1\n"
  "    return x\n"),
}
name, ver = sys.argv[1], sys.argv[2]
tmp = tempfile.mkdtemp(); pyc = os.path.join(tmp, "e.pyc")
compile_source(CASES[name], pyc, version=ver, dfile="<e>")
print(disassemble(pyc).get("text", ""))
