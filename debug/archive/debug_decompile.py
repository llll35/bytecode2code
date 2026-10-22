import sys
sys.path.insert(0, 'd:/py/bytecode2code')
from bytecode2code.pyc_parser import PyCParser
from bytecode2code.decompiler import Decompiler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
dec = Decompiler()
src = dec.decompile(pyc_file.code)
print(src)
