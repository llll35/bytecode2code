"""Scratch: what exception-table APIs does this interpreter offer?"""
import dis
import sys

print(sys.version.split()[0])
source = "def f():\n    try:\n        g()\n    except ValueError as e:\n        print(e)\n    finally:\n        h()\n"
code = compile(source, "x", "exec")
inner = [c for c in code.co_consts if hasattr(c, "co_code")][0]
print("co_exceptiontable present:", hasattr(inner, "co_exceptiontable"))
print("raw:", inner.co_exceptiontable)
print("decode():", inner.co_exceptiontable.decode())
print("_parse_exception_table:", dis._parse_exception_table(inner))
