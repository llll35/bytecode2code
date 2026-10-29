"""Port the block-close anchoring rule from 3.11 to the other 3.11+ backends.

``_place_one_close`` used to stop at the first nested handler, which cuts the
outer ``try`` of a ``try/except/else/finally`` short: the else clause's span
ends exactly where the ``except`` chain begins, so the close landed there and
the inline ``finally`` copy read as straight-line code after the block.  The
rule is now table-only -- take every span of this handler before the head, and
let the head-anchored fallback handle the chains that run up to the handler.
"""
import io
import sys

BEFORE = """        nested = [e.target for e in entries
                  if e.target != target and start < e.target <= target]
        limit = min(nested) if nested else target
        spans = [e for e in entries
                 if e.target == target and start <= e.start < limit]
"""
AFTER = """        spans = [e for e in entries
                 if e.target == target and start <= e.start < target]
"""
END_BEFORE = """        end = max(e.end for e in spans)
        index = self._offset_index(end)
        if index is None:
            index = len(raw_list)
        while index > 0 and raw_list[index - 1].offset in self._drops:
            index -= 1
"""
END_AFTER = """        end = max(e.end for e in spans)
        if end >= target:
            # The last span runs right up to the handler, so the block is never
            # closed inside its own region: 3.9 popped it on the way out of the
            # chain, in front of the handler head.
            self._close_before_head(raw_list, target, closes)
            return
        index = self._offset_index(end)
        if index is None:
            index = len(raw_list)
        stubs = self._unwind_stubs(entries)
        while index > 0 and (raw_list[index - 1].offset in self._drops
                             or any(lo <= raw_list[index - 1].offset < hi
                                    for lo, hi in stubs)):
            index -= 1
"""
STUB_BEFORE = """        stubs = []
        for entry in _exception_entries(self.code):
            begun = self._offset_index(entry.start)
            if begun is None or raw_list[begun].opname != 'COPY':
                continue
            stubs.append((entry.start, entry.end))
"""
STUB_AFTER = """        stubs = self._unwind_stubs(_exception_entries(self.code))
"""
HELPER = '''    def _unwind_stubs(self, entries):
        """Ranges the table protects that are only an unwinding stub.

        3.11 keeps an in-flight exception alive across a ``finally`` copy by
        running ``COPY`` / ``POP_EXCEPT`` / ``RERAISE``, and gives that stub a
        table entry of its own.  The emitter drops the instructions, so a block
        close must not land inside one: 3.9 wrote the pop where the *source*
        path ends, not where the unwinding stub sits.
        """
        out = []
        for entry in entries:
            index = self._offset_index(entry.start)
            if index is not None and self.raw[index].opname == 'COPY':
                out.append((entry.start, entry.end))
        return out

'''
MARK = "    def _close_before_head(self, raw_list, target, closes):"

for version in sys.argv[1:] or ["312", "313", "314", "315"]:
    path = "py%sDecompiler/decomp311.py" % version
    text = io.open(path, encoding="utf-8", newline="").read()
    endings = "\r\n" if "\r\n" in text else "\n"
    if HELPER.split("\n")[0] in text:
        print("already ported:", path)
        continue
    for name, (before, after) in (
        ("limit", (BEFORE, AFTER)),
        ("end", (END_BEFORE, END_AFTER)),
        ("stubs", (STUB_BEFORE, STUB_AFTER)),
        ("helper", (MARK, HELPER + MARK)),
    ):
        b, a = before.replace("\n", endings), after.replace("\n", endings)
        if b not in text:
            print("!! anchor missing (%s) in %s" % (name, path))
            break
        text = text.replace(b, a, 1)
    else:
        io.open(path, "w", encoding="utf-8", newline="").write(text)
        print("patched", path, "(%s endings)" % ("CRLF" if endings == "\r\n" else "LF"))
