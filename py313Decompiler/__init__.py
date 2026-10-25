"""Self-contained Python 3.13 decompiler."""
from .decompiler import Decompiler
from .decomp_compat import make_decompiler
from .decomp311 import Decompiler311
VERSION = "3.13"

__all__ = ["Decompiler", "VERSION", "Decompiler311", "decompile"]

def decompile(code):
    return make_decompiler(VERSION).decompile(code)
