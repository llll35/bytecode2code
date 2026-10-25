"""Self-contained Python 3.9 decompiler."""
from .decompiler import Decompiler
VERSION = "3.9"

__all__ = ["Decompiler", "VERSION", "decompile"]

def decompile(code):
    return Decompiler().decompile(code)
