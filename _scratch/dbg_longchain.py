"""Decompile the longchain probe in-process (base decompiler, 3.9)."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser
from bytecode2code import decompiler as dc

SOURCE = (
    "def f(a, b, c, d, e, g):\n"
    "    return a < b < c < d < e < g\n"
    "def h(a, b, c, d, e):\n"
    "    r = a < b <= c != d is e\n"
    "    return r, not (a < b < c < d < e)\n"
)

tmp = tempfile.mkdtemp()
pyc = os.path.join(tmp, "lc.pyc")
compile_source_to_pyc(SOURCE, pyc)
code = PyCParser.parse_file(pyc).code
print(dc.Decompiler().decompile(code))
