"""Compare source vs decompiled at the AST level, ignoring comments and formatting."""
import ast
import difflib
import sys

src = ast.parse(open(sys.argv[1], encoding="utf-8").read())
dec = ast.parse(open(sys.argv[2], encoding="utf-8").read())


def dump(node):
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def norm(node):
    """Render a node as readable source, one top-level item per entry."""
    return ast.unparse(node)


def walk(node, path="<module>"):
    yield path, node
    for field, value in ast.iter_fields(node):
        if isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, ast.AST):
                    tag = type(item).__name__
                    if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.If, ast.For, ast.While, ast.With, ast.Try, ast.ExceptHandler)):
                        p = "%s.%s[%d]" % (path, field, i)
                    else:
                        p = "%s.%s" % (path, field)
                    yield from walk(item, p)


a = dict((k, v) for k, v in walk(src))
b = dict((k, v) for k, v in walk(dec))

print("source nodes: %d   decompiled nodes: %d" % (len(a), len(b)))
print()

only_src = [k for k in a if k not in b]
only_dec = [k for k in b if k not in a]
if only_src:
    print("--- paths only in source (%d)" % len(only_src))
    for k in only_src[:20]:
        print("   ", k)
if only_dec:
    print("--- paths only in decompiled (%d)" % len(only_dec))
    for k in only_dec[:20]:
        print("   ", k)
print()

diffs = [k for k in a if k in b and dump(a[k]) != dump(b[k])]
print("--- differing shared paths (%d)" % len(diffs))
for k in diffs[:40]:
    print("  ", k)
    print("      src:", norm(a[k])[:160].replace("\n", " "))
    print("      dec:", norm(b[k])[:160].replace("\n", " "))
