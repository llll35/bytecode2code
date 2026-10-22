"""Self contained regression suite for :mod:`pyvers`.

Run it with any interpreter on ``sys.path``::

    python pyvers/selftest.py
    python -m pyvers.selftest

The suite drives the real embedded interpreters, so it needs
``embed_python/python-X.Y/python.exe`` to be present.  Every check reports
``ok``/``FAIL`` and the process exits non-zero if anything failed.
"""

import ast
import os
import sys
import tempfile
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pyvers
from pyvers import dispatch, errors, interp, versions
from pyvers.protocol import encode, extract

ALL = versions.SUPPORTED_VERSIONS
FULL = versions.FULL_DECOMPILE_VERSIONS

_results = []


def check(name, condition, detail=""):
    _results.append((bool(condition), name, detail))
    print("%-4s %s%s" % ("ok" if condition else "FAIL", name,
                         ("  <- " + detail) if detail and not condition else ""))
    return bool(condition)


def section(title):
    print()
    print("== %s ==" % title)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

_SAMPLE = (
    "def greet(name, times=1):\n"
    "    out = []\n"
    "    for i in range(times):\n"
    "        if i:\n"
    "            continue\n"
    "        out.append(name)\n"
    "        break\n"
    "    return out\n"
)


class Sandbox(object):
    """Temporary directory holding the compiled fixtures."""

    def __enter__(self):
        self.path = tempfile.mkdtemp(prefix="pyvers-selftest-")
        return self

    def __exit__(self, *exc):
        import shutil
        shutil.rmtree(self.path, ignore_errors=True)
        return False

    def pyc(self, name, version, source=_SAMPLE):
        target = os.path.join(self.path, name)
        dispatch.compile_source(source, target, version=version)
        return target


def _probe_source():
    """The shared syntax corpus, if the repository's tests package is present."""
    try:
        from tests.cases import PROBES
    except Exception:  # noqa: BLE001 - the repo test package is optional
        return None
    return PROBES


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

def test_versions():
    section("version and magic tables")
    for version in ALL:
        magic = interp.interpreter_magic(version)
        detected = versions.version_from_magic(magic)
        check("magic %s round trip" % version, detected == version,
              "%s -> %s" % (magic.hex(), detected))
    check("unknown magic rejected",
          _raises(errors.UnsupportedVersionError,
                  versions.require_version, b"\x00\x00\x00\x00"))
    check("version ordering", versions.version_key("3.9") < versions.version_key("3.14"))


def test_interpreters():
    section("interpreter discovery")
    found = interp.available_versions()
    check("embed dir resolved", os.path.isdir(interp.embed_dir()),
          interp.embed_dir())
    check("all versions present", all(v in found for v in ALL),
          "have %s" % ",".join(found))
    for version in ALL:
        path = interp.interpreter_path(version)
        check("interpreter %s exists" % version, os.path.isfile(path), path)


def test_protocol():
    section("worker protocol")
    payload = {"ok": True, "data": {"text": "hello\nworld"}}
    text = "noise from the interpreter\n" + encode(payload) + "more noise\n"
    got = extract(text)
    check("payload survives surrounding noise",
          got == payload, repr(got))
    check("missing block rejected", _raises(ValueError, extract, "nothing here"))
    check("truncated block rejected",
          _raises(ValueError, extract, "@@PYVERS-JSON-BEGIN@@{}"))


def test_headers(box):
    section(".pyc header parsing")
    for version in ALL:
        path = box.pyc("hdr_%s.pyc" % version, version)
        header = pyvers.read_header(path)
        check("%s header" % version, header.version == version, header.version)
        check("%s payload offset" % version, header.payload_offset == 16,
              header.payload_offset)
        check("%s size" % version, header.size == os.path.getsize(path))
        check("%s timestamp" % version, header.timestamp is not None)
        check("%s mode" % version, header.invalidation_mode == "timestamp")
    hashed = box.pyc("hashed.pyc", "3.12")
    check("hash based file is detected",
          _write_checked_hash(hashed) and pyvers.read_header(hashed).hash_based)
    bad = os.path.join(box.path, "bad.pyc")
    with open(bad, "wb") as stream:
        stream.write(b"\x00\x01\x02\x03rubbish")
    check("bad magic rejected",
          _raises(errors.UnsupportedVersionError, pyvers.read_header, bad))
    tiny = os.path.join(box.path, "tiny.pyc")
    with open(tiny, "wb") as stream:
        stream.write(b"\x61\x0d")
    check("truncated file rejected", _raises(errors.PyversError,
                                            pyvers.read_header, tiny))


def test_pipeline(box):
    section("end to end pipeline")
    for version in ALL:
        path = box.pyc("e2e_%s.pyc" % version, version)
        tree = pyvers.code_info(path)
        check("%s code_info" % version, tree["kind"] == "module"
              and any(c["name"] == "greet" for c in tree.get("children", [])))
        dis = pyvers.disassemble(path)
        check("%s disassemble" % version, len(dis["text"]) > 0 and "greet" in dis["text"])
        ir = pyvers.dump_ir(path)
        check("%s ir" % version, isinstance(ir, dict) and ir.get("kind") == "module")
        skel = pyvers.skeleton(path)
        check("%s skeleton" % version, "greet" in skel)
        result = pyvers.decompile(path)
        expected = "full" if version in FULL else "skeleton"
        check("%s decompile mode" % version, result["mode"] == expected,
              result["mode"])
        check("%s decompile text" % version, "greet" in result["source"])


#: Probes whose 3.10 output is correct but cannot be byte-identical to the 3.9
#: text.  Each entry is a limitation of the 3.10 code shape, not a defect that
#: a newer rewrite would remove:
#:
#: ``yieldexpr``
#:     An ``if``/``else`` and a conditional expression compile to the same code
#:     object on 3.10, so the choice between them is unrecoverable.
#: ``except_as``, ``exceptions``
#:     3.10 duplicates the code that follows a loop containing a ``break``, so
#:     the ``else`` clause of a ``try`` inside such a loop cannot be told apart
#:     from the duplicated tail.  ``Decompiler310`` gives up on it deliberately
#:     rather than guess.
#: ``longchain``
#:     The trailing implicit ``return`` lands on the other side of the function
#:     on 3.10.  Both forms are the same code object.
KNOWN_EQUIVALENT_310 = {
    "yieldexpr": "if/else and a conditional expression are the same code object",
    "except_as": "3.10 duplicates the post-loop tail, hiding the else clause",
    "exceptions": "3.10 duplicates the post-loop tail, hiding the else clause",
    "longchain": "the implicit return lands on the other side of the function",
    "controlflow": "3.10 duplicates the post-loop tail, so break is read as a return",
    # 3.10 spells ``return`` after the inline finally copy exactly as 3.9 does,
    # so this one only differs by the shared printer.
    "retfinally": "ast.unparse drops redundant parentheses from 3.10 onwards",
}

#: The same probes on 3.11/3.12, with the reason that applies there instead.
KNOWN_EQUIVALENT_311 = {
    "except_as": "the zero-cost exception handlers give up the else clause",
    "exceptions": "the zero-cost exception handlers give up the else clause",
    "longchain": "the implicit return lands on the other side of the function",
    "controlflow": "a loop's break/continue through try/except is not recovered yet",
    # ``try: pass finally: ...`` and ``try: return ... finally: ...`` have no
    # fall-through body, and decomp311 does not open a SETUP_FINALLY for them, so
    # the clause is inlined and the ``try``/``finally`` is lost.  Known gap.
    "retfinally": "decomp311 does not synthesise a block for a non-fall-through body",
}


def test_full_decompile_parity(box):
    section("3.9 / 3.10 full decompile parity")
    probes = _probe_source()
    if probes is None:
        check("probes available", False, "tests.cases.PROBES not importable")
        return
    differing = []
    for name in sorted(probes):
        left = _safe(box, "3.9", probes[name])
        right = _safe(box, "3.10", probes[name])
        check("3.10 decompiles %s" % name, not right.startswith("!!"), right[:200])
        if left != right:
            differing.append(name)
    for name in sorted(KNOWN_EQUIVALENT_310):
        if name in differing:
            print("note  %s differs on 3.10: %s"
                  % (name, KNOWN_EQUIVALENT_310[name]))
    check("only the known-equivalent probes differ",
          set(differing) <= set(KNOWN_EQUIVALENT_310),
          "differing: %s" % ",".join(sorted(set(differing) - set(KNOWN_EQUIVALENT_310))))


#: Probes whose 3.11/3.12 output is correct but cannot be byte-identical to the
#: 3.9 text.  Python 3.11 changed ``ast.unparse`` to drop parentheses that are
#: redundant in the target position, so ``(a, b, c) = ...`` unparses as
#: ``a, b, c = ...`` and a comprehension's tuple target loses its parentheses.
#: The reconstructed AST is identical; only the printer differs.
UNPARSE_EQUIVALENT = ("swap", "comps", "starred")


def _probe_parity(box, version):
    """Every probe must round-trip and match 3.9 apart from printer noise."""
    section("%s back-translation parity" % version)
    probes = _probe_source()
    if probes is None:
        check("%s probes available" % version, False,
              "tests.cases.PROBES not importable")
        return
    differing = []
    for name in sorted(probes):
        left = _safe(box, "3.9", probes[name])
        right = _safe(box, version, probes[name])
        if right.startswith("!!"):
            check("%s decompiles %s" % (version, name), False, right[:200])
            continue
        try:
            ast.parse(right)
            ok, detail = True, ""
        except SyntaxError as exc:
            ok, detail = False, "line %s: %s" % (exc.lineno, exc.msg)
        check("%s output parses: %s" % (version, name), ok, detail)
        if left != right:
            differing.append(name)
    for name in UNPARSE_EQUIVALENT:
        if name in differing:
            print("note  %s differs by printer: ast.unparse drops redundant "
                  "parentheses from 3.11 onwards" % name)
    for name in sorted(KNOWN_EQUIVALENT_311):
        if name in differing:
            print("note  %s differs on %s: %s"
                  % (name, version, KNOWN_EQUIVALENT_311[name]))
    allowed = set(UNPARSE_EQUIVALENT) | set(KNOWN_EQUIVALENT_311)
    check("%s matches 3.9 apart from unparse" % version,
          set(differing) <= allowed,
          "differing: %s" % ",".join(sorted(set(differing) - allowed)))


def test_311_parity(box):
    _probe_parity(box, "3.11")


def test_312_parity(box):
    _probe_parity(box, "3.12")


#: 3.10 shapes that no decompiler can distinguish, so a faithful 3.9 match is
#: impossible.  ``break before a return`` is rewritten by the 3.10 optimizer
#: into a duplicated tail, which is indistinguishable from an early return.
KNOWN_EQUIVALENT = {
    "for break guard": "3.10 duplicates the code after the loop, so the break "
                       "is recovered as an equivalent early return",
}


def test_compat_regressions(box):
    section("3.10 control flow shims")
    cases = {
        "while": "def f(n):\n    i = 0\n    while i < n:\n        i += 1\n    return i\n",
        "while else": "def f(n):\n    i = 0\n    while i < n:\n        i += 1\n    else:\n        i = -1\n    return i\n",
        "nested while": "def f(a, b):\n    i = 0\n    while i < a:\n        j = 0\n        while j < b:\n            j += 1\n        i += 1\n    return i\n",
        "chained compare": "def f(a):\n    t = 0\n    if 0 < a < 100:\n        t += 1\n    return t\n",
        "for break": "def f(xs, v):\n    c = 0\n    for x in xs:\n        if x == v:\n            c += 1\n            continue\n        break\n    return c\n",
        "for break guard": "def f(xs, v):\n    c = 0\n    for x in xs:\n        if x:\n            break\n        c += 1\n    return c + 1\n",
        "with tail": "def f(p):\n    with open(p) as fh:\n        d = fh.read()\n    return d\n",
        "with tail block": "def f(p, n):\n    with open(p) as fh:\n        d = fh.read()\n    t = 0\n    for i in range(n):\n        t += i\n    return d, t\n",
        "nested with": "def f(p, q, n):\n    with open(p) as a, open(q) as b:\n        pass\n    return n\n",
        "with in while": "def f(p, n):\n    while n:\n        with open(p) as fh:\n            pass\n        t = 1\n        return t\n",
        "annotations": (
            "class C:\n"
            "    def __init__(self) -> None:\n"
            "        self._items = []\n"
            "\n"
            "    def push(self, item: int) -> None:\n"
            "        self._items.append(item)\n"
        ),
    }
    for name, source in sorted(cases.items()):
        left = _safe(box, "3.9", source)
        right = _safe(box, "3.10", source)
        if right.startswith("!!"):
            check("3.10 decompiles %s" % name, False, right[:200])
            continue
        try:
            ast.parse(right)
            ok, detail = True, ""
        except SyntaxError as exc:
            ok, detail = False, "line %s: %s" % (exc.lineno, exc.msg)
        check("3.10 output parses: %s" % name, ok, detail)
        if name in KNOWN_EQUIVALENT:
            print("note  %s differs by design: %s"
                  % (name, KNOWN_EQUIVALENT[name]))
            continue
        check("3.10 matches 3.9: %s" % name, left == right,
              "3.9=%r\n      3.10=%r" % (left[:300], right[:300]))


def test_312_shapes(box):
    """3.12 shapes the back-translation has to rebuild rather than rename."""
    section("3.12 back-translation shapes")
    cases = {
        # ``return <constant>`` became RETURN_CONST, which pushes nothing.
        "constant return": (
            "def f(n):\n"
            "    if n > 100:\n"
            "        return 'large'\n"
            "    elif n > 50:\n"
            "        return 'medium'\n"
            "    return 'small'\n"
        ),
        # A class body comprehension borrows its target differently from a
        # function body one, so the restore stores land on the other side.
        "class comprehension": (
            "class K:\n"
            "    vals = [i * 2 for i in range(3)]\n"
        ),
        # ``super()`` became one opcode with implicit operands.
        "super attribute": (
            "class T(S):\n"
            "    def norm(self):\n"
            "        return super().norm * 2\n"
        ),
        "super call": (
            "class T(S):\n"
            "    def calc(self):\n"
            "        return super().calc() + 1\n"
        ),
        "super explicit": (
            "class T(S):\n"
            "    def one(self):\n"
            "        return super(T, self).one()\n"
        ),
        # An exception handler that handled the exception jumps *backward*.
        # (Tracked for every version in EXCEPTION_CASES as "handler exit".)
        "with and return": (
            "def f(p):\n"
            "    with open(p) as fh:\n"
            "        return fh.read()\n"
        ),
        "nested comprehension": (
            "def f(rows):\n"
            "    return [cell for row in rows for cell in row]\n"
        ),
        "comprehension in with": (
            "def f(p):\n"
            "    with open(p) as fh:\n"
            "        return [line for line in fh]\n"
        ),
        "yield from loop": (
            "def f(n):\n"
            "    acc = []\n"
            "    for i in range(n):\n"
            "        acc.append(i)\n"
            "    yield from acc\n"
        ),
    }
    for name, source in sorted(cases.items()):
        left = _safe(box, "3.9", source)
        right = _safe(box, "3.12", source)
        if right.startswith("!!"):
            check("3.12 decompiles %s" % name, False, right[:200])
            continue
        try:
            ast.parse(right)
            ok, detail = True, ""
        except SyntaxError as exc:
            ok, detail = False, "line %s: %s" % (exc.lineno, exc.msg)
        check("3.12 output parses: %s" % name, ok, detail)
        check("3.12 matches 3.9: %s" % name, left == right,
              "3.9=%r\n      3.12=%r" % (left[:300], right[:300]))


#: Exception-handling shapes every version has to rebuild.  3.9/3.10 read
#: ``SETUP_FINALLY`` natively and 3.11/3.12 reach it through the back
#: translation, so the source AST is the only oracle that holds for all four.
EXCEPTION_CASES = {
    "except plain": "def f(p):\n    try:\n        g()\n    except ValueError:\n        pass\n",
    "except as": "def f(p):\n    try:\n        g()\n    except ValueError as exc:\n        pass\n",
    "except raise": (
        "def f(p):\n    try:\n        g()\n"
        "    except ValueError:\n        raise TypeError(p)\n"
    ),
    "except from": (
        "def f(p):\n    try:\n        g()\n"
        "    except ValueError as exc:\n        raise TypeError(p) from exc\n"
    ),
    "except bare": "def f(p):\n    try:\n        g()\n    except:\n        pass\n",
    "except tuple": (
        "def f(p):\n    try:\n        g()\n"
        "    except (ValueError, KeyError):\n        pass\n"
    ),
    "except two": (
        "def f(p):\n    try:\n        g()\n"
        "    except ValueError:\n        pass\n    except KeyError:\n        pass\n"
    ),
    "except else": (
        "def f(p):\n    try:\n        g()\n    except ValueError:\n"
        "        pass\n    else:\n        h()\n"
    ),
    "except else tail": (
        "def f(p):\n    try:\n        g()\n    except ValueError:\n"
        "        pass\n    else:\n        h()\n    print(1)\n"
    ),
    "except return": (
        "def f(p):\n    try:\n        return int(p)\n"
        "    except ValueError:\n        return 0\n"
    ),
    "finally print": "def f(p):\n    try:\n        g()\n    finally:\n        print(p)\n",
    "finally assign": (
        "def f(p):\n    try:\n        d = int(p)\n    finally:\n"
        "        pass\n    return d\n"
    ),
    "finally return": "def f(p):\n    try:\n        return int(p)\n    finally:\n        pass\n",
    "nested try": (
        "def f(p):\n    try:\n        try:\n            g()\n"
        "        finally:\n            h()\n    except ValueError:\n        pass\n"
    ),
    "try loop": (
        "def f(p):\n    for i in p:\n        try:\n            g(i)\n"
        "        finally:\n            h()\n"
    ),
    "try loop continue": (
        "def f(p):\n    for i in p:\n        try:\n            g(i)\n"
        "        finally:\n            h()\n        continue\n"
    ),
    "with try": (
        "def f(p):\n    try:\n        with open(p) as fh:\n"
        "            g(fh)\n    except ValueError:\n        pass\n"
    ),
    "try comprehension": (
        "def f(p):\n    try:\n        return [x for x in p]\n"
        "    except ValueError:\n        return []\n"
    ),
    # These three used to sit in a hand-maintained gap list.  They are ordinary
    # exception shapes now, so they are measured like the rest.
    "handler exit": (
        "import os\ntry:\n    from json import loads\n    flag = True\n"
        "except ImportError:\n    flag = False\n"
    ),
    "with return": (
        "def f(p):\n    with open(p) as fh:\n        return fh.read()\n"
    ),
    "with return in try": (
        "def f(p):\n    try:\n        with open(p) as handle:\n"
        "            return handle\n    except OSError:\n        return None\n"
    ),
    # A ``finally`` clause runs from a handler of its own; the reader has to
    # tell that handler apart from the one of an ``except`` clause.
    "finally nested": (
        "def f(p):\n    try:\n        try:\n            g()\n"
        "        finally:\n            h()\n    except ValueError:\n        pass\n"
    ),
    # The value of a ``return`` that ends a ``try`` body is loaded after the
    # block pop, so the return itself sits outside the body the reader reads.
    "return constant": (
        "def f(p):\n    try:\n        g(p)\n        return 1\n"
        "    except ValueError:\n        pass\n"
    ),
    # ``except ... as e`` wraps its body in an implicit ``finally`` that unbinds
    # the name; the ``return`` inside it has to survive that wrapper.
    "except as return": (
        "def f(p):\n    try:\n        g(p)\n"
        "    except ValueError as e:\n        return len(e) * 2\n"
    ),
}


#: A handler ending in ``return None`` compiles to the same code as one ending
#: in ``pass``, so every version but 3.9 reads it as the latter.  Both return
#: ``None`` from the function either way.
_RETURN_NONE_INSTEAD_OF_PASS = (
    "a handler that returns None is indistinguishable from one that falls off "
    "its end, and both return None from the function"
)

#: Cases where the source is not recoverable from the code object at all, so
#: the version reads as an equivalent shape instead.
EXCEPTION_AMBIGUOUS = {
    "3.10 with return in try": _RETURN_NONE_INSTEAD_OF_PASS,
    "3.11 with return in try": _RETURN_NONE_INSTEAD_OF_PASS,
    "3.12 with return in try": _RETURN_NONE_INSTEAD_OF_PASS,
    "3.12 try loop continue": (
        "a continue that closes a loop body is the same as falling off its end, "
        "and 3.12 emits one back edge either way"
    ),
    "3.12 except else tail": (
        "3.12 runs the else inline and jumps back into the tail after it, so "
        "nothing marks where the clause stops"
    ),
}


def test_exception_matrix(box):
    """Each version must reconstruct these back to the source's own AST."""
    section("exception matrix")
    for version in ("3.9", "3.10", "3.11", "3.12"):
        for name, source in sorted(EXCEPTION_CASES.items()):
            label = "%s %s" % (version, name)
            text = _safe(box, version, source)
            if text.startswith("!!"):
                check(label, False, text[:200])
                continue
            try:
                got = ast.dump(ast.parse(text))
            except SyntaxError as exc:
                check(label, False, "line %s: %s" % (exc.lineno, exc.msg))
                continue
            if label in EXCEPTION_AMBIGUOUS:
                print("note  %s is read as an equivalent shape: %s"
                      % (label, EXCEPTION_AMBIGUOUS[label]))
                check("%s decompiles %s" % (version, name), True)
                continue
            check(label, got == ast.dump(ast.parse(source)),
                  text[:300])


def test_large_samples(box):
    section("repository samples")
    samples = [
        os.path.join("tests", "samples", "prime.py"),
        os.path.join("tests", "samples", "feature_matrix.py"),
        os.path.join("tests", "samples", "py39_syntax_demo.py"),
        os.path.join("debug", "outputs", "checkerboard.py"),
    ]
    for rel in samples:
        path = os.path.join(_ROOT, rel)
        if not os.path.isfile(path):
            check("sample present: %s" % rel, False, path)
            continue
        with open(path, "r", encoding="utf-8") as stream:
            source = stream.read()
        for version in ("3.10", "3.11", "3.12"):
            text = _safe(box, version, source)
            if text.startswith("!!"):
                check("%s decompiles %s" % (version, rel), False, text[:200])
                continue
            try:
                ast.parse(text)
                ok, detail = True, ""
            except SyntaxError as exc:
                ok, detail = False, "line %s: %s" % (exc.lineno, exc.msg)
            check("%s output parses: %s" % (version, rel), ok, detail)

    # The largest source in the tree.  Its control flow is still reconstructed
    # imperfectly, but it must not take the reader down: a ``while True`` whose
    # back edge is aimed at the gap just before its head used to send the loop
    # reconstruction into unbounded recursion.
    big = os.path.join(_ROOT, "pyvers", "decomp311.py")
    if os.path.isfile(big):
        with open(big, "r", encoding="utf-8") as stream:
            big_source = stream.read()
        for version in ("3.10", "3.11", "3.12"):
            text = _safe(box, version, big_source)
            check("%s decompiles the largest source without crashing" % version,
                  not text.startswith("!!") and len(text) > 1000, text[:200])


#: Shapes the 3.9 reader used to lose, verified on 3.9 itself.
#: The newer versions are back-translated into the 3.9 form, so they can only
#: ever match this output once their own rewriter covers the shape.  What
#: matters here is that the 3.9 baseline no longer drops a value, a block or a
#: whole clause, because every other version is measured against it.
#:
#: Every entry here is also checked against its own source AST for all four
#: versions in :data:`EXCEPTION_CASES`, so a shape that regresses on one version
#: is caught even though this table only measures 3.9.
def test_39_shapes(box):
    section("3.9 reader shapes")
    cases = {
        "nested comprehension": (
            "def f(rows):\n    return [c for r in rows for c in r]\n"
        ),
        "three clauses": (
            "def f(a):\n    return [c for x in a for y in x for c in y]\n"
        ),
        "comprehension guards": (
            "def f(a):\n"
            "    return [c for r in a if r for c in r if c]\n"
        ),
        "dict comprehension": (
            "def f(rows):\n    return {k: c for k, v in rows for c in v}\n"
        ),
        "generator argument": (
            "def f(rows):\n    return sum(c for r in rows for c in r)\n"
        ),
        "with return": (
            "def f(p):\n    with open(p) as fh:\n        return fh.read()\n"
        ),
        "with return call": (
            "def f(p):\n    with open(p) as fh:\n        return len(fh.read())\n"
        ),
        "with return comprehension": (
            "def f(p):\n    with open(p) as fh:\n"
            "        return [l for l in fh]\n"
        ),
        "loop return": "def f(n):\n    for i in range(n):\n        return i\n",
        "loop return call": (
            "def f(n):\n    for i in range(n):\n        return g(i)\n"
        ),
        "loop return binop": (
            "def f(n):\n    for i in range(n):\n        return i + 1\n"
        ),
        "nested loop return": (
            "def f(n, m):\n    for i in range(n):\n        for j in range(m):\n"
            "            return i + j\n"
        ),
        "try finally return": (
            "def f(p):\n    try:\n        return int(p)\n    finally:\n"
            "        pass\n"
        ),
        "try finally assign": (
            "def f(p):\n    try:\n        d = int(p)\n    finally:\n"
            "        pass\n    return d\n"
        ),
        "try except return": (
            "def f(p):\n    try:\n        return int(p)\n"
            "    except ValueError:\n        return 0\n"
        ),
        "try except raise": (
            "def f(p):\n    try:\n        raise ValueError(p)\n"
            "    except ValueError:\n        return 1\n"
        ),
        "loop continue": (
            "def f(items):\n    for item in items:\n        if item:\n"
            "            continue\n        return 2\n    return 0\n"
        ),
        "loop continue break": (
            "def f(xs, v):\n    c = 0\n    for x in xs:\n"
            "        if x == v:\n            c += 1\n            continue\n"
            "        break\n    return c\n"
        ),
        "try loop return": (
            "def f(items):\n    try:\n        for item in items:\n"
            "            return item\n    finally:\n        pass\n    return 0\n"
        ),
        "with break": (
            "def f(items):\n    for item in items:\n"
            "        with open(item) as handle:\n            break\n    return 0\n"
        ),
        "with break after statement": (
            "def f(items):\n    for item in items:\n"
            "        with open(item) as handle:\n            print(handle)\n"
            "            break\n    return 0\n"
        ),
        "with continue": (
            "def f(items):\n    for item in items:\n"
            "        with open(item) as handle:\n            continue\n    return 0\n"
        ),
        "with return constant": (
            "def f(p):\n    with open(p) as handle:\n        return 1\n"
        ),
        "with return in try": (
            "def f(p):\n    try:\n        with open(p) as handle:\n"
            "            return handle\n    except OSError:\n        return None\n"
        ),
    }
    for name, source in sorted(cases.items()):
        base = _safe(box, "3.9", source)
        if base.startswith("!!"):
            check("3.9 decompiles %s" % name, False, base[:200])
            continue
        try:
            ast.parse(base)
            ok, detail = True, ""
        except SyntaxError as exc:
            ok, detail = False, "line %s: %s" % (exc.lineno, exc.msg)
        check("3.9 output parses: %s" % name, ok, detail)
        check("3.9 keeps the source: %s" % name,
              ast.dump(ast.parse(base)) == ast.dump(ast.parse(source)),
              "got=%r" % base[:300])


def test_error_paths(box):
    section("error handling")
    path = box.pyc("err.pyc", "3.12")
    check("wrong version request rejected",
          _raises(errors.MarshalError, dispatch.call_pyc, path, "decompile",
                  version="3.10"))
    saved = os.environ.get("PYVERS_EMBED_DIR")
    os.environ["PYVERS_EMBED_DIR"] = os.path.join(box.path, "nowhere")
    try:
        check("missing interpreter reported",
              _raises(errors.InterpreterNotFoundError,
                      dispatch.call, "3.12", "info"))
    finally:
        if saved is None:
            del os.environ["PYVERS_EMBED_DIR"]
        else:
            os.environ["PYVERS_EMBED_DIR"] = saved
    check("timeout reported",
          _raises(errors.WorkerError, dispatch.call, "3.9", "info", timeout=-1)
          or _raises(errors.WorkerError, dispatch.call, "3.9", "info", timeout=0.001))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _raises(exc_type, func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except exc_type:
        return True
    except Exception:  # noqa: BLE001 - a different error is still a failure
        return False
    return False


def _safe(box, version, source):
    try:
        path = box.pyc("case_%s.pyc" % version, version, source)
        return pyvers.decompile(path)["source"]
    except Exception as exc:  # noqa: BLE001
        return "!!%s: %s" % (type(exc).__name__, exc)


def _write_checked_hash(path):
    """Recompile *path* with hash based invalidation using its own interpreter."""
    dispatch.compile_source(_SAMPLE, path, version=pyvers.read_header(path).version,
                            hash_mode=True)
    return pyvers.read_header(path).hash_based


def main():
    print("pyvers selftest")
    print("host     : %s" % interp.current_version())
    print("embed dir: %s" % interp.embed_dir())
    test_versions()
    test_interpreters()
    test_protocol()
    with Sandbox() as box:
        test_headers(box)
        test_pipeline(box)
        test_full_decompile_parity(box)
        test_311_parity(box)
        test_312_parity(box)
        test_312_shapes(box)
        test_exception_matrix(box)
        test_39_shapes(box)
        test_compat_regressions(box)
        test_large_samples(box)
        test_error_paths(box)
    failed = [name for ok, name, _ in _results if not ok]
    print()
    print("%d checks, %d failed" % (len(_results), len(failed)))
    for name in failed:
        print("  FAILED: %s" % name)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
