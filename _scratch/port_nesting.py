"""Scratch: port the nesting-aware block back-translation to py312..py315.

Copies five regions out of the already-patched ``py311Decompiler/decomp311.py``
and splices them into the other 3.11+ rewriters, asserting every anchor matches
exactly once.

    python _scratch/port_nesting.py
"""
import io
import re

REF = "py311Decompiler/decomp311.py"
TARGETS = ["py312Decompiler/decomp311.py", "py313Decompiler/decomp311.py"]


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def segment(text, first_marker, last_marker):
    start = text.index(first_marker)
    end = text.index(last_marker, start)
    return text[start:end]


ref = read(REF)

setups_seg = segment(ref, "    def _place_block_setups", "    def _offset_index")
close_head_seg = segment(ref, "    def _close_before_head", "    def _clause_shape")
emit_seg = segment(ref, "    def _emit_block_setups", "    def _translate_instruction")
not_spans_seg = segment(ref, "        if not spans:",
                        "        end = max(e.end for e in spans)")
BRANCH_OLD = """        if raw.offset in self.try_replace:
            out.extend(self._make(raw, op, a, v)
                       for op, a, v in self.try_replace[raw.offset])
            return index + 1
"""
BRANCH_NEW = segment(ref, "        if raw.offset in self.try_replace:",
                     "        following = raw_list[index + 1]")

OLD_INLINE = """        if raw.offset in self.try_setups:
            for target in self.try_setups[raw.offset]:
                out.append(self._make(raw, 'SETUP_FINALLY', raw.offset,
                                      target, line_no=None))
                if (raw.offset, target) in self.empty_body_setups:
                    # The inner ``try`` body is empty, so 3.9 closed it with a
                    # ``POP_BLOCK`` right after the ``SETUP_FINALLY``.
                    out.append(self._make(raw, 'POP_BLOCK', None, None,
                                          line_no=None))
"""


def once(text, needle, label):
    count = text.count(needle)
    if count != 1:
        raise SystemExit("%s: anchor %r found %d times" % (label, needle[:40], count))
    return text


for path in TARGETS:
    text = read(path)
    # 1. _place_block_setups (+ _region_start)
    text = once(text, "    def _place_block_setups", path)
    text = once(text, "    def _offset_index", path)
    head, rest = text.split("    def _place_block_setups", 1)
    old, tail = rest.split("    def _offset_index", 1)
    text = head + setups_seg + "    def _offset_index" + tail
    # 2. transitive close fallback
    text = once(text, "        if not spans:\n            return\n", path)
    text = text.replace("        if not spans:\n            return\n",
                        not_spans_seg)
    # 3. _close_before_head (the file's exit-copy helpers vary by version)
    marker = ("    def _clause_shape" if "    def _clause_shape" in text
              else "    def _place_one_close")
    text = once(text, marker, path)
    text = text.replace(marker, close_head_seg + marker, 1)
    # 4. the shared setup emitter
    text = once(text, OLD_INLINE, path)
    text = text.replace(OLD_INLINE, "        self._emit_block_setups(raw, out)\n")
    text = once(text, "    def _translate_instruction", path)
    text = text.replace("    def _translate_instruction",
                        emit_seg + "    def _translate_instruction", 1)
    # 5. emit the setups a rewritten handler head carries
    text = once(text, BRANCH_OLD, path)
    text = text.replace(BRANCH_OLD, BRANCH_NEW)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print("patched", path)
