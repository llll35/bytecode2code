"""Scratch: the raw exception table of a flow probe's function.

    embed_python/python-3.11/python.exe _scratch/exc_probe.py reraise_chain
"""
import dis
import importlib
import os
import py_compile
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.cases import FLOW_PROBES


def walk(code, seen):
    yield code
    for const in code.co_consts:
        if hasattr(const, "co_code"):
            yield from walk(const, seen)


name = sys.argv[1]
source = FLOW_PROBES[name]
print("### source")
print(source)

version = "%d.%d" % sys.version_info[:2]
pkg = "py%sDecompiler" % version.replace(".", "")
with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "p.py")
    pyc_path = os.path.join(tmp, "p.pyc")
    with open(src_path, "w", encoding="utf-8") as handle:
        handle.write(source)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)
    code = importlib.import_module(pkg + ".pyc_parser").PyCParser.parse_file(pyc_path).code

# `dis` needs a real code object; compiling on the running interpreter gives the
# same bytes as the pyc above.
code = compile(source, "probe.py", "exec")

def entries_of(target):
    """3.11 names the fields ``start``/``end``/``target``; 3.12+ ``*_offset``."""
    out = []
    for e in dis._parse_exception_table(target):
        field = lambda names: next(
            getattr(e, name) for name in names if hasattr(e, name)
        )
        out.append((field(("start", "start_offset")),
                    field(("end", "end_offset")),
                    field(("target", "target_offset")),
                    e.depth, e.lasti))
    return out


def dump(target):
    et = getattr(target, "co_exceptiontable", None)
    if not et:
        return
    entries = entries_of(target)
    print("--- %s  co_exceptiontable=%r" % (target.co_name, et))
    for start, end, target_off, depth, lasti in sorted(
            entries, key=lambda x: (x[0], x[2])):
        print("    start=%4d end=%4d target=%4d depth=%d lasti=%d"
              % (start, end, target_off, depth, lasti))
    by_off = {}
    for start, end, target_off, depth, lasti in sorted(entries):
        by_off.setdefault(start, []).append("<S%d>" % depth)
        by_off.setdefault(end, []).append("<E%d>" % depth)
        by_off.setdefault(target_off, []).append("<T%d>" % depth)
    print("    index | offset | opname")
    for i, ins in enumerate(dis.get_instructions(target)):
        print("    %3d | %5d | %-24s %-18s %s"
              % (i, ins.offset, ins.opname, ins.argrepr,
                 " ".join(by_off.get(ins.offset, []))))
    print()


print("### exception table + indexed dis, per code object")
for target in walk(code, set()):
    dump(target)
