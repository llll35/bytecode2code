import sys, os, marshal, dis

ROOT = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(ROOT, "pyvers"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import subprocess

import decomp311

with open(sys.argv[1], "rb") as h:
    top = marshal.loads(h.read()[16:])

print("Top-level code:", top.co_name)
print("Exception entries:")
for e in decomp311._exception_entries(top):
    print(f"  start={e.start}, end={e.end}, target={e.target}, depth={e.depth}, lasti={e.lasti}")

r = decomp311.Rewriter(top)
shape = r.analyse()
print()
print("Raw instructions:")
for raw in r.raw:
    print(f"  offset={raw.offset}, opname={raw.opname}, argval={raw.argval}")
print()
print("_tails_at_merge:", getattr(r, '_tails_at_merge', 'NOT SET'))
print("_retarget:", getattr(r, '_retarget', 'NOT SET'))
print("_drops:", getattr(r, '_drops', 'NOT SET'))