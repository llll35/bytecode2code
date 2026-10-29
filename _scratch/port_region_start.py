"""Scratch: port the nested-head region start and the bare-finally drop.

Two regions move from the patched 3.11 rewriter to 3.12 -- 3.15:

``_region_start`` (+ ``_table_heads``)
    a handler dispatch that lies inside a region pulls the synthesised
    ``SETUP_FINALLY`` back to its own body, which is where 3.9 pushed it.
``_analyse_handlers``
    a ``finally`` handler is 3.9's clause copy with no marker in front, so the
    ``PUSH_EXC_INFO`` 3.11 left there goes.

    python _scratch/port_region_start.py
"""
import io

REF = "py311Decompiler/decomp311.py"
TARGETS = ["py312Decompiler/decomp311.py", "py313Decompiler/decomp311.py",
           "py314Decompiler/decomp311.py", "py315Decompiler/decomp311.py"]

FINALLY_OLD = """                # ``DUP_TOP`` the reader uses to recognise a clause, so it is
                # left as it is.
                continue
"""
FINALLY_NEW = """                # ``DUP_TOP`` the reader uses to recognise a clause, so it is
                # left as it is -- and without the marker either: 3.9 pushed the
                # exception triple with the ``SETUP_FINALLY`` itself, so its
                # clause begins at the first instruction of the handler.  Leaving
                # ``PUSH_EXC_INFO`` in front of it makes the reader stop the
                # clause before it starts and print an empty ``finally``.
                self._drops.add(entry.target)
                continue
"""


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def segment(text, first_marker, last_marker):
    start = text.index(first_marker)
    return text[start:text.index(last_marker, start)]


def once(text, needle, label):
    if text.count(needle) != 1:
        raise SystemExit("%s: anchor %r found %d times"
                         % (label, needle[:40], text.count(needle)))
    return text


ref = read(REF)
region_seg = segment(ref, "    def _region_start", "    def _offset_index")

for path in TARGETS:
    text = read(path)
    once(text, "    def _region_start", path)
    once(text, "    def _offset_index", path)
    head, rest = text.split("    def _region_start", 1)
    _old, tail = rest.split("    def _offset_index", 1)
    text = head + region_seg + "    def _offset_index" + tail

    once(text, FINALLY_OLD, path)
    text = text.replace(FINALLY_OLD, FINALLY_NEW)

    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print("patched", path)
