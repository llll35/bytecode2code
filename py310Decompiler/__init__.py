# Python 3.10 Decompiler
from bytecode2code.decompiler import Decompiler as Base

class Decompiler(Base):
    """3.10 control-flow restored."""
    _copied_none_return = True
