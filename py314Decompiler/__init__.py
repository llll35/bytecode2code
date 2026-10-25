"""Self-contained Python 3.14 decompiler."""
from .decompiler import Decompiler
VERSION = "3.14"

__all__ = ["Decompiler", "VERSION", "decompile"]

def decompile(code):
    return Decompiler().decompile(code)
