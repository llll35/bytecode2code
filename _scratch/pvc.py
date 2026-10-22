import sys
sys.path.insert(0, r"D:\py\bytecode2code")
from bytecode2code import Decompiler as Base
import bytecode2code.decompiler as D
import inspect
src = inspect.getsource(Base._parse_value_chain)
print(src)
