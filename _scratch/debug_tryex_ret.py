"""Re-examine try/except + return bytecode in Python 3.9."""
import dis, os, py_compile, sys, tempfile

SRC = (
    "def n():\n"
    "    try:\n"
    "        return 5\n"
    "    except ValueError:\n"
    "        return 6\n"
)

with tempfile.TemporaryDirectory() as tmp:
    src_path = os.path.join(tmp, "n.py")
    pyc_path = os.path.join(tmp, "n.pyc")
    with open(src_path, "w") as f: f.write(SRC)
    py_compile.compile(src_path, cfile=pyc_path, doraise=True)

    import marshal
    with open(pyc_path, "rb") as f:
        f.read(16)
        code = marshal.load(f)

    print("=== Full bytecode ===")
    dis.dis(code)

    # List instructions properly
    print("\n=== Instruction table ===")
    co = code
    ops = co.co_code
    i = 0
    idx = 0
    entries = []
    while i < len(ops):
        offset = i
        op = ops[i]; i += 1
        name = dis.opname[op]
        arg = None
        if op >= dis.HAVE_ARGUMENT:
            arg = ops[i] | (ops[i+1] << 8)
            i += 2
        entries.append((idx, offset, name, arg))
        idx += 1

    # Collect jump targets
    targets = set()
    for _, _, name, arg in entries:
        if arg is not None and name in dis.hasjabs | dis.hasjrel:
            if name in dis.hasjabs:
                targets.add(arg)
            else:
                targets.add(offset + arg)

    for idx, offset, name, arg in entries:
        mark = ">>" if offset in targets else "  "
        print(f"  {mark} {idx:3d}  {offset:4d}  {name:20s}  arg={arg}")

    print("\n=== Key observations ===")
    # Find SETUP_FINALLY
    for idx, offset, name, arg in entries:
        if name == "SETUP_FINALLY":
            print(f"  SETUP_FINALLY at idx={idx}, offset={offset}, arg={arg}")
            # Find POP_BLOCK
            for j in range(idx+1, len(entries)):
                if entries[j][2] == "POP_BLOCK":
                    print(f"  POP_BLOCK at idx={j}, offset={entries[j][1]}")
                    # After POP_BLOCK
                    for k in range(j+1, min(j+5, len(entries))):
                        print(f"    idx={k}: {entries[k][2]} @ {entries[k][1]}")
                    break
