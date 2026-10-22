import json
a = json.load(open(r"D:\py\bytecode2code\_scratch\lc39.json"))
b = json.load(open(r"D:\py\bytecode2code\_scratch\lc312.json"))
a = [x for x in a if x["op"] not in ("RESUME","NOP")]
print("39 len", len(a), "312 len", len(b))
for i,(x,y) in enumerate(zip(a,b)):
    if x != y:
        print(i, x, "  |  ", y)
