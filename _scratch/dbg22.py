"""Replicate ExceptionAnalyzer.regions() with a trace of how each POP_BLOCK
got attributed to a setup, so the over-collection can be seen.

Run with the interpreter of the target bytecode version.
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests.cases import FLOW_PROBES
from py39Decompiler.cfg_flow import build_cfg, _SETUP_OPS, _BLOCK_POPS, classify_handler

name = sys.argv[1] if len(sys.argv) > 1 else "nested_finally_reraise"
src = FLOW_PROBES[name]
code = compile(src, "<t>", "exec")
f = [k for k in code.co_consts if hasattr(k, "co_code")][0]
pkg = "py%d%dDecompiler" % sys.version_info[:2]
import importlib
mod = importlib.import_module(pkg + ".decompiler")
d = mod.Decompiler()
instructions = d._insert_dead_block_closes(d.dis.disassemble(f))
offset_to_index = {i.offset: p for p, i in enumerate(instructions)}

# --- setup_sites
sites = []
for position, instr in enumerate(instructions):
    if instr.opname in _SETUP_OPS:
        t = instr.argval
        if t is not None and int(t) in offset_to_index:
            sites.append((position, instr.opname, offset_to_index[int(t)]))

cfg = build_cfg(instructions)
regions = {}
for position, setup_op, handler in sites:
    kind = classify_handler(instructions, handler, setup_op)
    regions[position] = [setup_op, kind, position + 1, None, [(handler, kind)], []]

entry = cfg.entry.number
pending = [(entry, (), ())]      # (block, stack, route)
seen = set()
handler_of = {p: h for p, _, h in sites}
closes = {}
owner = cfg.owner
while pending:
    number, stack, route = pending.pop()
    if (number, stack) in seen:
        continue
    seen.add((number, stack))
    block = cfg.blocks[number]
    route = route + (number,)
    for index in range(block.start, block.end):
        nm = instructions[index].opname
        if nm in _SETUP_OPS:
            h = handler_of.get(index)
            if h is not None:
                pending.append((owner[h], stack, route + ("H%d" % h,)))
            if index not in stack:
                stack = stack + (index,)
        elif nm in _BLOCK_POPS and stack:
            setup = stack[-1]
            stack = stack[:-1]
            closes.setdefault(setup, set()).add(index)
            print("close %4d -> setup %4d (%s) route %s" %
                  (index, setup, instructions[setup].opname, route))
    for succ in block.successors:
        pending.append((succ, stack, route))

print("---- summary ----")
for setup in sorted(closes):
    print("setup", setup, instructions[setup].opname,
          "-> handler", handler_of[setup], "pops", sorted(closes[setup]))
