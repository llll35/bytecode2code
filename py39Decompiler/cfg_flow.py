"""Control-flow graph, dominator tree and exception regions.

The reader in ``decompiler.py`` reconstructs block boundaries by scanning the
flat instruction list forward for the opcode that ``looks`` like the end of a
block.  That is where the project's recurring control-flow defects come from:
a ``POP_BLOCK`` belonging to an enclosing ``with``, a loop back edge that is
also a ``continue``, a ``finally`` handler that is really a bare ``except``.
This module answers the same questions from the graph instead:

``build_cfg``
    basic blocks with explicit successors and predecessors.
``CFG.dominators``
    immediate dominators, the dominator tree and dominance frontiers, so
    "which region does this edge close" is a reachability fact rather than a
    guess from the next few opcodes.
``ExceptionAnalyzer``
    protected ranges and handler roles, read from the block stack
    (``SETUP_FINALLY`` / ``SETUP_EXCEPT`` / ``SETUP_WITH`` / ``BEFORE_WITH``)
    that a ``SETUP_*`` site names.  That is what a 3.9/3.10 stream -- and the
    3.9-shaped stream 3.11+ is back-translated into before the reader sees it --
    actually carries.  Reading ``co_exceptiontable`` directly, so 3.11+ needs no
    back-translation, is the goal of this engine but is **not implemented**:
    today the analyzer is blind to a stream whose ``finally`` region the
    rewriter has already inlined away.
"""

import dis
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

#: Opcodes that transfer control and do not fall through.
_UNCONDITIONAL = frozenset((
    "JUMP_ABSOLUTE", "JUMP_FORWARD", "JUMP", "RERAISE", "RETURN_VALUE",
    "RETURN_CONST", "RAISE_VARARGS", "END_FINALLY", "BREAK_LOOP",
    "CONTINUE_LOOP", "RETURN_GENERATOR", "YIELD_VALUE",
))

#: Opcodes that push a block whose handler is named in the operand.
_SETUP_OPS = frozenset((
    "SETUP_FINALLY", "SETUP_EXCEPT", "SETUP_ASYNC", "SETUP_WITH",
    "BEFORE_WITH",
))

#: Opcodes that end a protected region on the normal path.
_BLOCK_POPS = frozenset(("POP_BLOCK",))

#: Conditional branches: fall through *and* jump.
_CONDITIONAL_JUMPS = frozenset((
    "POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE", "POP_JUMP_IF_NONE",
    "POP_JUMP_IF_NOT_NONE", "JUMP_IF_FALSE_OR_POP", "JUMP_IF_TRUE_OR_POP",
    "JUMP_IF_NOT_EXC_MATCH",
))

_LOOP_HEADS = frozenset(("FOR_ITER",))

#: Opcodes whose operand is an address in this code object.  Every other
#: operand is a constant index, an argument count or a name index that merely
#: *looks* like an address, and reading it as one invents an edge: the
#: ``RAISE_VARARGS 0`` of a bare ``raise`` and the ``RERAISE 0`` that closes a
#: handler chain both name the number of values on the stack, and offset 0 is
#: the function entry, so the walk would jump there with the block stack it
#: carried and credit the entry's region with every close downstream.
_TARGETED_OPS = frozenset((
    "JUMP_ABSOLUTE", "JUMP_FORWARD", "JUMP", "JUMP_BACKWARD",
    "BREAK_LOOP", "CONTINUE_LOOP",
)) | _CONDITIONAL_JUMPS | _SETUP_OPS | _LOOP_HEADS


@dataclass
class Block:
    """One basic block, as a half-open range over the instruction list."""

    number: int
    start: int
    end: int
    #: opname of the block's last instruction, set when the graph is built
    terminator: str = ""
    successors: List[int] = field(default_factory=list)
    predecessors: List[int] = field(default_factory=list)


@dataclass
class CFG:
    """Directed graph over the basic blocks of one code object."""

    instructions: Sequence
    blocks: List[Block]
    #: instruction index -> block number
    owner: Dict[int, int]

    def __post_init__(self):
        self._by_number = {b.number: b for b in self.blocks}

    @property
    def entry(self) -> Block:
        return self.blocks[0]

    def block_at(self, index: int) -> Optional[Block]:
        number = self.owner.get(index)
        return self._by_number.get(number) if number is not None else None

    def reachable(self, start_index: int, exclude: FrozenSet[int] = frozenset()) -> Set[int]:
        """Instruction indices reachable from *start_index* by normal flow.

        *exclude* names instruction indices that must not be entered -- handler
        entries, for instance.  Walking edges rather than the flat list is what
        keeps a handler's ``POP_BLOCK`` from being mistaken for the body's.
        """
        block = self.block_at(start_index)
        if block is None:
            return set()
        seen: Set[int] = set()
        stack = [block.number]
        while stack:
            number = stack.pop()
            if number in seen:
                continue
            seen.add(number)
            for succ in self._by_number[number].successors:
                if self._by_number[succ].start in exclude:
                    continue
                stack.append(succ)
        return {index for number in seen
                for index in range(self._by_number[number].start,
                                   self._by_number[number].end)}

    def dominators(self) -> Dict[int, int]:
        """Block number -> immediate dominator, via Cooper-Harvey-Kennedy.

        The entry dominates itself, so it is absent from the result.
        """
        order = self._reverse_post_order()
        idom: Dict[int, int] = {order[0]: order[0]}
        changed = True
        while changed:
            changed = False
            for number in order[1:]:
                block = self._by_number[number]
                preds = [p for p in block.predecessors if p in idom]
                if not preds:
                    continue
                new = preds[0]
                for pred in preds[1:]:
                    new = self._intersect(new, pred, idom, order)
                if idom.get(number) != new:
                    idom[number] = new
                    changed = True
        root = order[0]
        idom.pop(root, None)
        return idom

    def dominance_frontier(self, idom: Dict[int, int]) -> Dict[int, List[int]]:
        """Blocks that join just below *number* -- the region close points.

        For every edge ``P -> B``, ``B`` is in ``P``'s frontier unless ``B``
        strictly dominates ``P``; walking ``P`` up the dominator tree to
        ``idom(B)`` enumerates exactly those edges.
        """
        frontier: Dict[int, List[int]] = {block.number: [] for block in self.blocks}
        for block in self.blocks:
            for pred in block.predecessors:
                runner = pred
                while runner is not None and runner != idom.get(block.number):
                    if block.number not in frontier[runner]:
                        frontier[runner].append(block.number)
                    runner = idom.get(runner)
        return frontier

    def _intersect(self, a: int, b: int, idom: Dict[int, int],
                  order: List[int]) -> int:
        index = {number: position for position, number in enumerate(order)}
        while a != b:
            while index[a] > index[b]:
                a = idom[a]
            while index[b] > index[a]:
                b = idom[b]
        return a

    def _reverse_post_order(self) -> List[int]:
        order: List[int] = []
        visiting: Set[int] = set()
        done: Set[int] = set()

        def visit(number: int):
            if number in done or number in visiting:
                return
            visiting.add(number)
            for succ in self._by_number[number].successors:
                visit(succ)
            visiting.discard(number)
            done.add(number)
            order.append(number)

        visit(self.entry.number)
        order.reverse()
        return order


def _jump_target(instr, offset_to_index: Dict[int, int]) -> Optional[int]:
    """Instruction index a jump/SETUP operand points at."""
    if instr.opname not in _TARGETED_OPS or instr.argval is None:
        return None
    try:
        offset = int(instr.argval)
    except (TypeError, ValueError):
        return None
    return offset_to_index.get(offset)


def build_cfg(instructions: Sequence) -> CFG:
    """Split *instructions* into basic blocks and wire the edges.

    A block starts at the first instruction, at any jump or handler target, and
    after any terminator or conditional branch -- the classical rules, plus the
    ``SETUP_*`` operands, which name a handler entry no jump points at.
    """
    offset_to_index = {instr.offset: position
                       for position, instr in enumerate(instructions)}
    names = [instr.opname for instr in instructions]

    leaders: Set[int] = {0}
    for position, instr in enumerate(instructions):
        if instr.opname in _SETUP_OPS or instr.opname in _CONDITIONAL_JUMPS \
                or instr.opname in _UNCONDITIONAL or instr.opname in _LOOP_HEADS:
            if position + 1 < len(instructions):
                leaders.add(position + 1)
        target = _jump_target(instr, offset_to_index)
        if target is not None:
            leaders.add(target)

    ordered = sorted(leaders)
    blocks: List[Block] = []
    owner: Dict[int, int] = {}
    for number, start in enumerate(ordered):
        end = ordered[number + 1] if number + 1 < len(ordered) else len(instructions)
        blocks.append(Block(number=number, start=start, end=end,
                            terminator=names[end - 1]))
        for index in range(start, end):
            owner[index] = number

    def _block_of(index: int) -> int:
        return owner[index]

    for block in blocks:
        last = block.end - 1
        name = names[last]
        jump = _jump_target(instructions[last], offset_to_index)
        if name in _CONDITIONAL_JUMPS or name in _LOOP_HEADS:
            # FOR_ITER falls through to the body only while the iterator has
            # items; the exhausted path is its operand.  Both are edges.
            if jump is not None:
                block.successors.append(_block_of(jump))
            if last + 1 < len(instructions):
                block.successors.append(_block_of(last + 1))
        elif name in _UNCONDITIONAL:
            # A jump goes to its operand and nowhere else; RETURN/RAISE/RERAISE
            # have no successor in this code object -- RERAISE resumes the
            # enclosing region's handler, which is an exception edge, not this.
            if jump is not None:
                block.successors.append(_block_of(jump))
            elif (name in ("RAISE_VARARGS", "RERAISE")
                    and last + 1 < len(instructions)
                    and names[last + 1] == "POP_BLOCK"):
                # A ``raise`` unwinds the block it is raised from, yet the
                # compiler still emits that block's own ``POP_BLOCK`` behind it
                # -- 3.9 as dead code, 3.10 nowhere at all.  That pop is where
                # the protected range ends, and a walk that cannot reach it
                # closes the range on an earlier exit path -- taking the
                # statement that left the block for its last one.  A
                # ``RERAISE`` sits behind every handler chain that does not
                # swallow the exception, so it guards the enclosing region's
                # close the same way the raise that produced it does.
                block.successors.append(_block_of(last + 1))
        else:
            if last + 1 < len(instructions):
                block.successors.append(_block_of(last + 1))

    for block in blocks:
        block.successors = sorted(set(block.successors))
    for block in blocks:
        for succ in block.successors:
            blocks[succ].predecessors.append(block.number)
    for block in blocks:
        block.predecessors = sorted(set(block.predecessors))
    return CFG(instructions=instructions, blocks=blocks, owner=owner)


#: Roles a handler entry can play, decided from the shape of its first
#: instructions rather than from which opcode pushed it: 3.9 spells every
#: ``try`` clause with ``SETUP_FINALLY``, so the opcode name says nothing.
KIND_EXCEPT = "except"
KIND_FINALLY = "finally"
KIND_AS_CLEANUP = "as_cleanup"
KIND_WITH = "with"


@dataclass
class Region:
    """One protected range: the setup site, its body and its handlers."""

    setup_index: int
    #: opname that opened the region
    setup_op: str
    kind: str
    #: half-open instruction range of the body on the normal path
    body_start: int
    body_end: Optional[int]
    #: handler entries reached exceptionally from this region
    handlers: List[Tuple[int, str]] = field(default_factory=list)
    #: every POP_BLOCK that closes this region on a path that never unwound into
    #: a handler, ascending.  A body that can leave early -- ``break``,
    #: ``continue``, ``return`` -- pops the block on that path and again on the
    #: normal one, so a region has more than one.
    body_pops: List[int] = field(default_factory=list)
    #: closes reached only by falling through a handler it encloses.  3.10 and
    #: later paste the ``finally`` clause -- and the code behind the ``try`` --
    #: in front of every exit, so a handler's exit looks like a second normal
    #: close of the enclosing region, one the body's text stops short of.
    exit_pops: List[int] = field(default_factory=list)

    @property
    def last_body_pop(self) -> Optional[int]:
        """The outermost closing pop, which is where the body's text ends."""
        return self.body_pops[-1] if self.body_pops else self.body_end

    def covers(self, index: int) -> bool:
        return (self.body_start <= index
                and self.body_end is not None and index < self.body_end)


def _opname(instructions, index) -> str:
    if index is None or index < 0 or index >= len(instructions):
        return ""
    return instructions[index].opname


def classify_handler(instructions, entry: int, setup_op: str = "") -> str:
    """What role the handler at *entry* plays.

    ``DUP_TOP`` followed by ``JUMP_IF_NOT_EXC_MATCH`` is an ``except`` chain:
    the exception is duplicated so each clause's type test can bail out to the
    re-raise.  ``LOAD_CONST None / STORE_FAST / DELETE_FAST / RERAISE`` is the
    cleanup the compiler wraps around an ``except ... as name`` body so the name
    is unbound on every exit, including an exception raised inside it.  A
    ``with`` region is named by its own setup opcode.  Anything else runs
    unconditionally on exit, which is ``finally``.
    """
    if setup_op in ("SETUP_WITH", "SETUP_ASYNC", "BEFORE_WITH"):
        return KIND_WITH
    window = [instr.opname for instr in instructions[entry:entry + 8]]
    if not window:
        return KIND_FINALLY
    if window[0] == "DUP_TOP" and "JUMP_IF_NOT_EXC_MATCH" in window[:4]:
        return KIND_EXCEPT
    if (window[0] == "LOAD_CONST" and instructions[entry].argval is None
            and len(window) > 3
            and window[1] in ("STORE_FAST", "STORE_NAME", "STORE_DEREF")
            and window[2] in ("DELETE_FAST", "DELETE_NAME", "DELETE_DEREF")
            and window[3] in ("RERAISE", "END_FINALLY")):
        return KIND_AS_CLEANUP
    if "WITH_EXCEPT_START" in window[:3]:
        return KIND_WITH
    return KIND_FINALLY


class ExceptionAnalyzer:
    """Protected ranges and handler roles for one code object.

    ``SETUP_*`` sites are matched to the ``POP_BLOCK`` that closes them by
    simulating the block stack along the CFG's normal-flow edges, with handler
    entries excluded from the walk.  The old reader scanned forward from the
    setup and took the first plausible ``POP_BLOCK``, which is why an enclosing
    ``with``'s pop, or a handler's own pop, could be read as the body's end.
    """

    def __init__(self, instructions: Sequence, cfg: Optional[CFG] = None):
        self.instructions = instructions
        self.cfg = cfg if cfg is not None else build_cfg(instructions)
        self._offset_to_index = {instr.offset: position
                                 for position, instr in enumerate(instructions)}

    def setup_sites(self) -> List[Tuple[int, str, int]]:
        """``(setup index, opname, handler index)`` for every block push."""
        sites = []
        for position, instr in enumerate(self.instructions):
            if instr.opname in _SETUP_OPS:
                target = _jump_target(instr, self._offset_to_index)
                if target is not None:
                    sites.append((position, instr.opname, target))
        return sites

    def regions(self) -> List[Region]:
        """Match each ``SETUP_*`` to the ``POP_BLOCK`` that closes its body.

        The walk follows the CFG's normal-flow edges while carrying the block
        stack the interpreter would have held: push at every ``SETUP_*``, pop at
        every ``POP_BLOCK``.  A handler entry is never reached by normal flow,
        so a handler's own ``POP_BLOCK`` cannot be mistaken for the body's --
        and neither can an enclosing ``with``'s pop, which is how bugs 8, 9 and
        11 in ``bugs.md`` were introduced by the forward scan.
        """
        sites = self.setup_sites()
        regions: Dict[int, Region] = {}
        for position, setup_op, handler in sites:
            kind = classify_handler(self.instructions, handler, setup_op)
            regions[position] = Region(
                setup_index=position, setup_op=setup_op, kind=kind,
                body_start=position + 1, body_end=None,
                handlers=[(handler, kind)])

        entry_block = self.cfg.entry.number
        # (block number, block stack) pairs already simulated.  The stack is
        # part of the visit key because a join can be reached both with a loop's
        # entry block still on the stack and with it already popped.  Each entry
        # carries whether the path reaching it unwound into a handler after the
        # region was pushed, which is what separates the body's own close from
        # the copy of it an exception exit runs.
        pending = [(entry_block, ())]
        seen: Set[Tuple[int, tuple]] = set()
        handler_of = {position: handler for position, _, handler in sites}
        closes: Dict[int, Set[int]] = {}
        unwound: Dict[int, Set[int]] = {}
        while pending:
            number, stack = pending.pop()
            if (number, stack) in seen:
                continue
            seen.add((number, stack))
            block = self.cfg.blocks[number]
            for index in range(block.start, block.end):
                name = _opname(self.instructions, index)
                if name in _SETUP_OPS:
                    # Unwinding to this region's handler discards the block the
                    # setup pushed, so the handler runs with the stack as it was
                    # before the push.  Without that edge the regions nested
                    # inside a handler -- the cleanup guard around
                    # ``except ... as name``, the inline copy of a ``finally`` --
                    # are never simulated and stay without a body end.
                    handler = handler_of.get(index)
                    if handler is not None:
                        pending.append((
                            self.cfg.owner[handler],
                            tuple((setup, True) for setup, _ in stack)))
                    if index not in {setup for setup, _ in stack}:
                        # A loop re-entering its own region arrives over the
                        # back edge with the region already on the stack;
                        # pushing again would grow the simulation without
                        # bound.  The fresh entry is untainted: from here on it
                        # is this region that is running, however it was reached.
                        stack = stack + ((index, False),)
                elif name in _BLOCK_POPS and stack:
                    setup, tainted = stack[-1]
                    stack = stack[:-1]
                    region = regions.get(setup)
                    if region is not None:
                        (unwound if tainted else closes).setdefault(
                            setup, set()).add(index)
                        if region.body_end is None:
                            region.body_end = index
            for succ in block.successors:
                pending.append((succ, stack))

        # A body whose last statement raises, returns or breaks out has no
        # POP_BLOCK at all -- the compiler lets the unwind leave the block --
        # so the walk above never closes it.  Its end is a reachability fact
        # instead: everything normal flow can still be in before the region
        # closes or a handler begins.
        entries = {handler for _, _, handler in sites}
        for region in regions.values():
            own = closes.get(region.setup_index, frozenset())
            extra = unwound.get(region.setup_index, frozenset()) - own
            # A region whose only closes sit behind a handler -- one the
            # exception path alone reaches, because every normal exit returns --
            # keeps those copies: they are the only record the graph has of where
            # it ends.
            region.body_pops = sorted(own or extra)
            region.exit_pops = sorted(extra) if own else []
            if region.body_end is None:
                region.body_end = self._body_by_reachability(
                    region.setup_index, entries)
        return [regions[position] for position in sorted(regions)]

    def _body_by_reachability(self, setup: int, entries: Set[int]) -> Optional[int]:
        """End of a region that never pops its own block.

        Walks normal flow from the instruction after the setup and stops at the
        first block holding a ``POP_BLOCK`` (that pop belongs to some region)
        and never enters a handler entry.
        """
        block = self.cfg.block_at(setup + 1)
        if block is None:
            return None
        seen: Set[int] = set()
        stack = [block.number]
        indices: List[int] = []
        while stack:
            number = stack.pop()
            if number in seen:
                continue
            seen.add(number)
            current = self.cfg.blocks[number]
            for index in range(current.start, current.end):
                if _opname(self.instructions, index) in _BLOCK_POPS:
                    break
                indices.append(index)
            if _opname(self.instructions, current.end - 1) in _BLOCK_POPS:
                continue
            for succ in current.successors:
                if self.cfg.blocks[succ].start in entries:
                    continue
                stack.append(succ)
        return max(indices) + 1 if indices else None

    def innermost_region(self, index: int) -> Optional[Region]:
        """The tightest protected range whose body holds *index*."""
        best = None
        for region in self.regions():
            if region.covers(index) and (best is None
                                         or region.body_start > best.body_start):
                best = region
        return best


