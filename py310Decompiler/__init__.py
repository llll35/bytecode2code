"""Self-contained Python 3.10 decompiler."""
from .decompiler import Decompiler
from .decomp_compat import Decompiler310, decompiler_for, make_decompiler
VERSION = "3.10"

__all__ = ["Decompiler", "VERSION", "Decompiler310", "decompile", "decompiler_for", "make_decompiler"]

def decompile(code):
    return make_decompiler(VERSION).decompile(code)
