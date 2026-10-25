"""Self-contained Python 3.13 decompiler."""
from .decompiler import Decompiler
VERSION = "3.13"

__all__ = ["Decompiler", "VERSION", "decompile"]

def decompile(code):
    return Decompiler().decompile(code)
