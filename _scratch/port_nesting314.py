"""Scratch: port the nesting-aware block back-translation to py314 / py315.

Those two already emit ``SETUP_FINALLY`` at the very top of
``_translate_instruction`` -- ahead of the handler rewrite -- so only the
transitive region start, the shared emitter and the close fallback move over.

    python _scratch/port_nesting314.py
"""
import io

REF = "py311Decompiler/decomp311.py"
TARGETS = ["py314Decompiler/decomp311.py", "py315Decompiler/decomp311.py"]

OLD_INLINE = """        if raw.offset in self.try_setups:
            for target in self.try_setups[raw.offset]:
                out.append(self._make(raw, 'SETUP_FINALLY', raw.offset,
                                      target, line_no=None))
                if (raw.offset, target) in self.empty_body_setups:
                    out.append(self._make(raw, 'POP_BLOCK', None, None,
                                          line_no=None))
"""


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def segment(text, first_marker, last_marker):
    start = text.index(first_marker)
    return text[start:text.index(last_marker, start)]


def once(text, needle, label):
    count = text.count(needle)
    if count != 1:
        raise SystemExit("%s: anchor %r found %d times" % (label, needle[:40], count))
    return text


ref = read(REF)
setups_seg = segment(ref, "    def _place_block_setups", "    def _offset_index")
close_head_seg = segment(ref, "    def _close_before_head", "    def _clause_shape")
emit_seg = segment(ref, "    def _emit_block_setups", "    def _translate_instruction")
not_spans_seg = segment(ref, "        if not spans:",
                        "        end = max(e.end for e in spans)")

for path in TARGETS:
    text = read(path)
    text = once(text, "    def _place_block_setups", path)
    text = once(text, "    def _offset_index", path)
    head, rest = text.split("    def _place_block_setups", 1)
    _old, tail = rest.split("    def _offset_index", 1)
    text = head + setups_seg + "    def _offset_index" + tail

    text = once(text, "        if not spans:\n            return\n", path)
    text = text.replace("        if not spans:\n            return\n", not_spans_seg)

    text = once(text, "    def _clause_shape", path)
    text = text.replace("    def _clause_shape",
                        close_head_seg + "    def _clause_shape", 1)

    text = once(text, OLD_INLINE, path)
    text = text.replace(OLD_INLINE, "        self._emit_block_setups(raw, out)\n")

    text = once(text, "    def _translate_instruction", path)
    text = text.replace("    def _translate_instruction",
                        emit_seg + "    def _translate_instruction", 1)

    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print("patched", path)
