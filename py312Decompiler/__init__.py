"""Self-contained Python 3.12 decompiler."""
from .decompiler import Decompiler
from .decomp_compat import Decompiler310, make_decompiler
from .decomp311 import Decompiler311

VERSION = "3.12"

__all__ = ["Decompiler", "VERSION", "Decompiler310", "Decompiler311", "decompile", "make_decompiler"]

def decompile(code):
    return make_decompiler(VERSION).decompile(code)
