import dis
names = [n for n in dis.opmap if "LOAD_FAST" in n or "INTRINSIC" in n or n in ("IMPORT_STAR",)]
print(sorted(names))
for n in sorted(names):
    print(n, dis.opmap[n])
