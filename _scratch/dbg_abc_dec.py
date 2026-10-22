"""Decompile the retfinally source with the BASE decompiler in-process.

Run under the 3.9 embedded interpreter:
  embed_python/python-3.9/python.exe -B _scratch/dbg_abc_dec.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bytecode2code.main import compile_source_to_pyc
from bytecode2code.pyc_parser import PyCParser
from bytecode2code import decompiler as dc

SOURCE = (
    "def a():\n"
    "    try:\n"
    "        return 1\n"
    "    finally:\n"
    "        x = 1\n"
    "def b():\n"
    "    try:\n"
    "        return 1\n"
    "    finally:\n"
    "        pass\n"
    "def c(n):\n"
    "    try:\n"
    "        return n + 1\n"
    "    finally:\n"
    "        y = n * 2\n"
    "    return y\n"
)

tmp = tempfile.mkdtemp()
pyc = os.path.join(tmp, "rf.pyc")
compile_source_to_pyc(SOURCE, pyc)
code = PyCParser.parse_file(pyc).code
print(dc.Decompiler().decompile(code))
