"""Give every 3.11+ rewriter the 'clause only exists in the handler' case.

``Decompiler311._collect_finally_body`` shadows the 3.9 reader's recovery with a
version of its own that assumes an inline copy always sits between the block
pop and the handler.  When every path runs the clause and escapes there is no
such copy and the clause reads as ``pass``.  Hand that case back to the reader.
"""
import io

MARK = ("        if handler_start_idx <= try_end_idx or "
        "handler_start_idx >= len(instructions):\n"
        "            return [], None\n")

SEGMENT = MARK + """
        if try_end_idx + 1 == handler_start_idx:
            # Nothing was pasted between the block pop and the handler: every
            # path that leaves this ``try`` runs the clause and escapes -- a
            # ``return`` in the body, a ``return`` in the clause -- so there is
            # no normal path to carry an inline copy and the handler's copy is
            # the only text the clause ever got.  The 3.9 reader reads the
            # clause there and resumes past the handler.
            return super()._collect_finally_body(
                code, instructions, try_end_idx, handler_start_idx
            )
"""

for version in ("311", "312", "313", "314", "315"):
    path = "py%sDecompiler/decomp311.py" % version
    with io.open(path, encoding="utf-8", newline="\n") as handle:
        text = handle.read()
    if MARK not in text:
        print("skip (no guard):", path)
        continue
    if "if try_end_idx + 1 == handler_start_idx:" in text:
        print("already patched:", path)
        continue
    text = text.replace(MARK, SEGMENT, 1)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print("patched", path)
