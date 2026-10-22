"""Temporary: strip a method body down to the construct that breaks the reader."""
import ast
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pyvers  # noqa: E402
from pyvers import dispatch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "pyvers", "decomp311.py")


def try_source(version, source):
    with tempfile.TemporaryDirectory(prefix="st_") as folder:
        pyc = os.path.join(folder, "m.pyc")
        try:
            dispatch.compile_source(source, pyc, version=version, dfile="<s>")
            got = pyvers.decompile(pyc)["source"]
        except Exception as exc:
            return "ERR %s" % (type(exc).__name__), None
    try:
        ast.parse(got)
    except SyntaxError:
        return "SYNTAX", got
    return ("ok" if ast.dump(ast.parse(got)) == ast.dump(ast.parse(source))
            else "DIFF"), got


def extract(name):
    with open(TARGET, "r", encoding="utf-8") as f:
        lines = f.readlines()
    tree = ast.parse("".join(lines))

    def search(body):
        for node in body:
            if getattr(node, "name", None) == name:
                return node
            if isinstance(node, ast.ClassDef):
                found = search(node.body)
                if found is not None:
                    return found
        return None

    node = search(tree.body)
    return "".join(lines[node.lineno - 1:node.end_lineno])


def as_method(source):
    return "class C:\n" + source


def main():
    version = "3.9"
    name = "analyse"
    raw = extract(name)
    status, got = try_source(version, as_method(raw))
    print("%-30s %s" % (name, status))
    if status != "ERR":
        return
    print("--- got ---")
    print(got)
    tree = ast.parse(as_method(raw))
    fn = tree.body[0].body[0]
    print("--- statements: %d ---" % len(fn.body))
    for n, stmt in enumerate(fn.body):
        piece = "class C:\n" + ast.unparse(ast.Module(
            body=[ast.ClassDef(name="C", bases=[], keywords=[],
                               body=[ast.FunctionDef(
                                   name="f", args=ast.arguments(
                                       posonlyargs=[], args=[], vararg=None,
                                       kwonlyargs=[], kw_defaults=[],
                                       kwarg=None, defaults=[]),
                                   body=[stmt], decorator_list=[])],
                               decorator_list=[])],
            type_ignores=[]))
        status, out = try_source(version, piece)
        print("  [%2d] %-12s %s" % (n, type(stmt).__name__, status))
        if status == "ERR":
            print(ast.unparse(stmt)[:400])


if __name__ == "__main__":
    main()