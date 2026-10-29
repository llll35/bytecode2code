"""Trace the reader's finally-related calls for one probe."""
import importlib
import os
import py_compile
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.cases import FLOW_PROBES

name = sys.argv[1]
source = FLOW_PROBES[name]
version = "%d.%d" % sys.version_info[:2]
pkg = "py%sDecompiler" % version.replace(".", "")
mod = importlib.import_module(pkg + ".decompiler")

cls = next(v for k, v in vars(mod).items()
           if isinstance(v, type) and "_collect_finally_body" in v.__dict__)
print("### defining class", cls.__name__)

TARGETS = ["_collect_finally_body", "_hide_escape_copies", "_is_bare_finally",
           "_parse_except_handlers", "_find_pop_block", "_collect_finally_body",
           "_find_target_idx", "_handler_prologue_start", "_return_value_after_pop_block"]

for meth in sorted(set(TARGETS)):
    if not hasattr(cls, meth):
        print("!! missing", meth)
        continue
    def make(meth):
        original = getattr(cls, meth)
        import inspect
        def wrapper(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            if meth == "_is_bare_finally":
                print("[%s] handler=%s -> %s"
                      % (meth, args[1], result))
            else:
                shown = args[1:]
                print("[%s] %s -> %r"
                      % (meth, shown if meth != "_parse_except_handlers" else
                         (args[1], args[2], args[3]),
                         result if not isinstance(result, list) or len(result) < 4
                         else "<%d items>" % len(result)))
            return result
        return wrapper
    setattr(cls, meth, make(meth))

parser = importlib.import_module(pkg + ".pyc_parser")
with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "p.py")
    pyc_path = os.path.join(tmp, "p.pyc")
    with open(src_path, "w", encoding="utf-8") as handle:
        handle.write(source)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)
    from tests.test_roundtrip import decompile_sample
    print("### decompiled")
    print(decompile_sample(pyc_path))
