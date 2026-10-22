"""Run inside an embedded interpreter: real `dis` output for every code object.

    embed_python\\python-3.12\\python.exe -B _scratch\\dump_native.py <pyc>
"""
import dis
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from pyvers import worker
from pyvers.pycfile import read_header

path = sys.argv[1]
code = worker.load_code(path, read_header(path).payload_offset)


def walk(c):
    print("--- %s ---" % c.co_name)
    dis.dis(c)
    for const in c.co_consts:
        if hasattr(const, "co_code"):
            walk(const)


walk(code)