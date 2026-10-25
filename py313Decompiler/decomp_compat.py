"""Version-specific shims around :class:`bytecode2code.Decompiler`.

The stock decompiler assumes the Python 3.9 code shapes it was written
against.  Python 3.10 keeps the same opcode numbering but the peephole
optimizer lays conditional loops out differently, so a few control-flow
sniffers in the original code no longer match.  Python 3.11 renamed the
opcodes outright and 3.12 changed how comprehensions, ``super()`` and
exception handlers are compiled; both are handled by ``decomp311``, which
feeds this 3.10 decompiler a 3.9 shaped view of the instruction stream.  The
subclasses here restore the 3.9 behaviour by recognising the newer shapes,
without touching the original package.
"""

import ast
from typing import Any, List, Optional, Tuple

from .decompiler import Decompiler as _BaseDecompiler

_JUMP_OPS = ("JUMP_ABSOLUTE", "JUMP_FORWARD")
_POP_JUMPS = ("POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE")


class Decompiler310(_BaseDecompiler):
    """``Decompiler`` with Python 3.10 control-flow shapes restored."""

    #: 3.10 copies the implicit ``return None`` of the enclosing function into
    #: every ``except`` handler instead of sharing one tail.  ``decomp311``
    #: clears the flag because its rewriter already drops those copies.
    _copied_none_return = True

    def _drop_copied_return(self, body: List[ast.stmt]) -> List[ast.stmt]:
        """Remove the trailing ``return None`` a 3.10 handler carries.

        3.9 ends a handler with ``POP_EXCEPT`` and a jump to the function's
        single implicit ``LOAD_CONST None; RETURN_VALUE``.  3.10 duplicates
        that pair per handler, so the handler body ends in a return that the
        source never wrote.

        An explicit ``return None`` compiles to the same pair and leaves no
        trace to tell the two apart: ``except E: pass else: h()`` and
        ``except E: return None; h()`` are byte-for-byte identical, in 3.10 as
        much as in 3.9.  Both are therefore read as the ``else`` form, which is
        the shape the copy almost always comes from.
        """
        if not body:
            return body
        tail = body[-1]
        if isinstance(tail, ast.Return) \
                and isinstance(tail.value, ast.Constant) \
                and tail.value.value is None:
            body = body[:-1]
        return body or [ast.Pass()]

    def _parse_handler_body(
        self,
        code,
        instructions,
        body_start: int,
        as_setup_target,
        as_setup_idx,
        fallback_reraise_idx: int,
    ) -> Tuple[List[ast.stmt], int]:
        body, post = super()._parse_handler_body(
            code, instructions, body_start, as_setup_target, as_setup_idx,
            fallback_reraise_idx,
        )
        if not self._copied_none_return:
            return body, post
        return self._drop_copied_return(body), post

    @staticmethod
    def _implicit_return_at(instructions, idx: int) -> int:
        """End index of the ``LOAD_CONST None; RETURN_VALUE`` pair at *idx*.

        Returns *idx* itself when no such pair starts there.
        """
        if idx + 1 >= len(instructions):
            return idx
        first, second = instructions[idx], instructions[idx + 1]
        if first.opname == "LOAD_CONST" and first.argval is None \
                and second.opname == "RETURN_VALUE":
            return idx + 2
        return idx

    def _collect_finally_body(
        self, code, instructions, try_end_idx: int, handler_start_idx: int
    ):
        """Step over the implicit return 3.10 parks after the inline clause.

        3.9 closes the inline copy with a jump over the handler and reaches the
        function's implicit return afterwards.  3.10 has no jump there, so the
        ``LOAD_CONST None; RETURN_VALUE`` pair lands right where the jump would
        be and would otherwise be decompiled as a statement of its own.
        """
        finalbody, resume = super()._collect_finally_body(
            code, instructions, try_end_idx, handler_start_idx
        )
        if self._copied_none_return and resume is not None:
            end = self._implicit_return_at(instructions, resume)
            if end != resume:
                self._handled_ranges.append((resume, end))
                resume = end
        return finalbody, resume

    def _recover_else_clause(
        self,
        code,
        instructions,
        try_end_idx: int,
        handler_start_idx: int,
        post: int,
    ) -> List[ast.stmt]:
        """Look for the clause only where 3.10 can actually leave one.

        3.10 still places an ``else`` clause after the handler, reached by the
        jump that closes the try body, so there is nothing in the gap between
        the body and the handler.  What does sit there is the copied implicit
        return plus whatever the handler of a ``with`` or ``finally`` the body
        opened left behind, all of which :meth:`_recover_else_clause` would
        otherwise read as the clause.
        """
        if not self._copied_none_return:
            return super()._recover_else_clause(
                code, instructions, try_end_idx, handler_start_idx, post
            )
        return []

    def _with_exit_terminator(
        self, instructions, pop_idx: int, limit: int, body_value: bool = False
    ) -> int:
        """Stop the teardown at the enclosing block 3.10 closes after it.

        3.9 jumps over the ``with`` handler and reaches the function's implicit
        return later, so the ``LOAD_CONST None; RETURN_VALUE`` the reader finds
        after the teardown can only be a value the body returned.  3.10 closes
        the enclosing ``try`` there instead and parks the copied implicit return
        right behind it, which the reader would read as ``return None``.
        """
        term_idx = super()._with_exit_terminator(
            instructions, pop_idx, limit, body_value
        )
        if not self._copied_none_return or term_idx < 1:
            return term_idx
        if instructions[term_idx - 1].opname == "POP_BLOCK" \
                and self._implicit_return_at(instructions, term_idx) != term_idx:
            return term_idx - 1
        return term_idx

    def _filter_block_closes(
        self,
        instructions,
        setup_idx: int,
        try_end_idx: int,
        candidates,
    ):
        """Drop the close a ``with`` block's own handler emits.

        3.10 parks a ``with`` block's handler *after* the close of the ``try``
        that contains it, and the handler closes the ``with`` block a second
        time so that the unwind path pops it as well.  3.9 put the handler in
        front of the ``try``'s close, so there was only ever one close to
        choose from.

        Without the filter the handler's close is read as the end of the
        ``try`` body, and the code the ``try`` was supposed to protect ends up
        in the ``else`` clause instead.
        """
        if not self._copied_none_return:
            return candidates
        if instructions[setup_idx].opname in ("SETUP_WITH", "SETUP_ASYNC_WITH"):
            return candidates
        handlers = []
        for i in range(setup_idx + 1, try_end_idx):
            if instructions[i].opname not in ("SETUP_WITH", "SETUP_ASYNC_WITH"):
                continue
            target = self._jump_target(instructions[i])
            if target is None:
                continue
            handler = self._find_target_idx(instructions, target)
            if handler is not None:
                handlers.append(handler)
        if not handlers:
            return candidates
        return [i for i in candidates if not any(i >= h for h in handlers)]

    def _find_while_cond(
        self, instructions, start: int, end: int
    ) -> Optional[Tuple[int, int, int]]:
        """Detect ``while cond:`` on the 3.10 layout, then fall back to 3.9.

        3.10 duplicates the condition at the bottom of the body and closes the
        loop with ``POP_JUMP_IF_TRUE`` back to the *body* start instead of
        ending the body with ``JUMP_ABSOLUTE`` to the *condition* head.  The
        3.9 sniff would latch onto a ``continue`` (``JUMP_ABSOLUTE`` to the
        condition head) instead, so the 3.10 shape must be tried first.
        """
        found = self._find_while_cond_310(instructions, start, end)
        if found is not None:
            return found
        return super()._find_while_cond(instructions, start, end)

    def _find_while_cond_310(
        self, instructions, start: int, end: int
    ) -> Optional[Tuple[int, int, int]]:
        if start >= end or start >= len(instructions):
            return None
        head = instructions[start]
        if head.opname in ("FOR_ITER", "GET_ITER") + _POP_JUMPS:
            return None
        if head.offset in self._loop_heads:
            return None
        j = start
        while j < end:
            op = instructions[j].opname
            if op in _POP_JUMPS:
                break
            if op not in self._COND_EXPR_OPS:
                return None
            j += 1
        if j >= end or j + 1 >= len(instructions):
            return None
        guard = instructions[j]
        # 3.12 inverts the guard: the condition jumps *into* the body and the
        # unconditional jump behind it leaves the loop, aimed back at the
        # enclosing loop's iterator.  3.10/3.11 keep the guard in front and jump
        # forward to the exit instead.
        if (guard.opname == "POP_JUMP_IF_TRUE"
                and j + 2 < len(instructions)
                and self._jump_target(guard) == instructions[j + 2].offset
                and instructions[j + 1].opname in _JUMP_OPS):
            body_start = j + 2
            body_offset = instructions[body_start].offset
            exit_idx = self._find_target_idx(
                instructions, self._jump_target(instructions[j + 1])
            )
        else:
            exit_idx = self._find_target_idx(
                instructions, self._jump_target(guard)
            )
            if exit_idx <= j:
                return None
            # The 3.10 back edge jumps to the first instruction *after* the guard.
            body_offset = instructions[j + 1].offset
            body_start = j + 1
        # 3.10 exits when the condition turns false and jumps back on
        # ``POP_JUMP_IF_TRUE``; 3.12 kept the duplicated condition but guards it
        # with ``POP_JUMP_IF_FALSE`` followed by an unconditional back edge.
        # Either instruction identifies the same body start.
        back_jump = None
        if exit_idx > body_start:
            for k in range(body_start, exit_idx):
                ins = instructions[k]
                if ins.opname not in _POP_JUMPS and ins.opname not in _JUMP_OPS:
                    continue
                if self._jump_target(ins) == body_offset:
                    back_jump = k
                    break
        else:
            # The exit points back at an enclosing loop, so there is no forward
            # target to bound the body with: scan until the loop's own exit
            # jump, the next backward jump that does not return to the body.
            for k in range(body_start, len(instructions)):
                ins = instructions[k]
                if ins.opname not in _POP_JUMPS and ins.opname not in _JUMP_OPS:
                    continue
                target = self._jump_target(ins)
                if target == body_offset:
                    back_jump = k
                    break
                if target is not None and target < ins.offset:
                    break
        if back_jump is None:
            return None
        # ``back_jump`` sits *after* the duplicated condition; the body ends
        # where that copy starts.  3.12 guards the copy with a pop-jump of its
        # own before the unconditional back edge, so step over that too.
        body_end = back_jump
        if instructions[body_end - 1].opname in _POP_JUMPS:
            body_end -= 1
        while body_end - 1 > j and instructions[body_end - 1].opname in self._COND_EXPR_OPS:
            body_end -= 1
        if body_end == back_jump:
            return None
        loop_end = max(
            exit_idx, self._compute_loop_end(instructions, start, back_jump)
        )
        return j, body_end, loop_end

    def _find_while_true_back_edge(
        self, instructions, start: int, end: int
    ) -> Optional[int]:
        """Also match a 3.10 ``while True`` whose head is preceded by a ``NOP``.

        3.10 emits ``NOP`` for the statement and jumps back to the first real
        body instruction, so the back-edge target is not the statement offset.
        """
        found = super()._find_while_true_back_edge(instructions, start, end)
        if found is not None:
            return found
        head = start
        while head < end and instructions[head].opname == "NOP":
            head += 1
        if head == start or head >= end:
            return None
        body_offset = instructions[head].offset
        if body_offset in self._loop_heads:
            return None
        found = None
        for j in range(head, end):
            ins = instructions[j]
            if ins.opname in _JUMP_OPS and self._jump_target(ins) == body_offset:
                found = j
        return found

    def _process_call(self, opname, instr, stack, stmts):
        """Restore the 3.9 operand order for a comprehension call.

        3.11 still built a nested code object, but called it with
        ``CALL 0`` because the iterator was already on the stack beneath it,
        so ``CALL`` carries ``argc=0`` where 3.9 had ``CALL_FUNCTION 1``.

        3.12 dropped the nested code object altogether and evaluates the
        iterable *before* it has anything to call, which leaves the
        comprehension object on top of its own argument rather than beneath
        it.  Both layouts have to be swapped back so the callable is the one
        the comprehension object replaced.
        """
        from .decompiler import _CompMaker
        if opname != "CALL_FUNCTION":
            return super()._process_call(opname, instr, stack, stmts)
        argc = instr.arg or 0
        if not argc and len(stack) >= 2:
            for node in reversed(stack[-2:]):
                if isinstance(node, _CompMaker):
                    instr.arg = 1
                    break
        elif argc == 1 and len(stack) >= 2 \
                and isinstance(stack[-1], _CompMaker):
            stack[-1], stack[-2] = stack[-2], stack[-1]
        return super()._process_call(opname, instr, stack, stmts)

    @staticmethod
    def _as_annotation_dict(node):
        """Rebuild the 3.10 flat annotation tuple as a ``Dict``.

        3.9 assembles annotations with ``BUILD_CONST_KEY_MAP``.  3.10 pushes
        the keys and values interleaved and closes them with ``BUILD_TUPLE``
        (or a single constant tuple), so the operand arrives as a flat tuple
        instead of the ``Dict`` the stock decompiler expects.
        """
        if isinstance(node, ast.Dict):
            return node
        if isinstance(node, ast.Constant) and isinstance(node.value, tuple):
            elts = [ast.Constant(value=item) for item in node.value]
        elif isinstance(node, ast.Tuple):
            elts = list(node.elts)
        else:
            return None
        if len(elts) < 2 or len(elts) % 2:
            return None
        keys = elts[0::2]
        if not all(
            isinstance(k, ast.Constant) and isinstance(k.value, str) for k in keys
        ):
            return None
        return ast.Dict(keys=keys, values=elts[1::2])

    def _process_make_function(self, instr, stack, stmts, code) -> int:
        """Normalise the 3.10 annotation operand, then fall back to 3.9."""
        if (instr.arg or 0) & 0x04 and len(stack) >= 3:
            # MAKE_FUNCTION pops qualname, then the code object, then the
            # annotation operand, so it always sits third from the top.
            stack[-3] = self._as_annotation_dict(stack[-3]) or stack[-3]
        return super()._process_make_function(instr, stack, stmts, code)

    def _with_has_exit_jump(self, instructions, pop_idx: int, handler_start: int) -> bool:
        """True when a jump already skips the ``SETUP_WITH`` cleanup block."""
        for j in range(pop_idx, handler_start):
            if instructions[j].opname in _JUMP_OPS:
                if self._find_target_idx(
                    instructions, self._jump_target(instructions[j])
                ) >= handler_start:
                    return True
        return False

    def _find_with_cleanup_end(self, instructions, handler_start: int) -> Optional[int]:
        """Index right after the ``POP_EXCEPT``/``POP_TOP`` that closes a handler."""
        total = len(instructions)
        i = handler_start
        while i < total and instructions[i].opname != "POP_EXCEPT":
            i += 1
        if i >= total:
            return None
        i += 1
        if i < total and instructions[i].opname == "POP_TOP":
            i += 1
        return i

    def _find_with_tail_end(self, instructions, start: int, hard_end: int) -> int:
        """End of the straight-line block that starts at ``start``."""
        i = start
        while i < hard_end:
            ins = instructions[i]
            if i > start and (ins.is_jump_target or ins.opname in self._STMT_START_OPS):
                break
            i += 1
        return i

    def _process_with(
        self, instr, instructions, idx: int, code, stack, stmts
    ) -> int:
        """Rebuild ``with`` on the 3.10 layout, then fall back to 3.9.

        3.9 ends the normal path with a ``JUMP_FORWARD`` that skips the implicit
        ``__exit__`` handler, so the handler is never walked again.  3.10 drops
        that jump and duplicates the straight-line code that follows the block
        instead -- once inline, once after the nested exit call, and once after
        the handler -- so every copy past the first has to be marked consumed.
        A tail containing control flow keeps its ``JUMP_FORWARD`` and never
        reaches this path.
        """
        before = len(stmts)
        consumed = super()._process_with(instr, instructions, idx, code, stack, stmts)
        if len(stmts) == before or not isinstance(stmts[-1], (ast.With, ast.AsyncWith)):
            return consumed
        handler_start = self._find_target_idx(instructions, self._jump_target(instr))
        pop_idx = self._find_pop_block(instructions, idx, self._jump_target(instr))
        if not (idx < pop_idx <= handler_start):
            return consumed
        if self._with_has_exit_jump(instructions, pop_idx, handler_start):
            return consumed
        merge = self._find_stmt_run_end(instructions, pop_idx, handler_start)
        cleanup_end = self._find_with_cleanup_end(instructions, handler_start)
        if merge >= handler_start or cleanup_end is None:
            return consumed
        tail_end = self._find_with_tail_end(instructions, merge, handler_start)
        if tail_end < handler_start:
            self._handled_ranges.append((tail_end, handler_start))
        duplicated = handler_start - merge
        self._handled_ranges.append(
            (handler_start, min(cleanup_end + duplicated, len(instructions)))
        )
        return consumed

    def _find_duplicated_tail(self, instructions, idx: int, end_idx: int) -> int:
        """Largest ``s`` with ``instructions[s:end_idx]`` repeated at ``end_idx``.

        3.10 elides the jump of a ``break`` that closes a loop body and
        duplicates the code after the loop in its place, so the copy sitting
        right before the loop's exit target is recognisable by repetition.
        """
        total = len(instructions)
        span = end_idx - idx
        best = None
        for s in range(end_idx - 1, idx, -1):
            length = end_idx - s
            if length > span or end_idx + length > total:
                break
            for k in range(length):
                left = instructions[s + k]
                right = instructions[end_idx + k]
                if left.opname != right.opname or left.arg != right.arg:
                    break
            else:
                best = s
        return best

    def _process_loop(
        self, instr, instructions, idx, code, stack, stmts, limit=None
    ) -> int:
        """Restore the ``break`` that 3.10 elides at the end of a ``for`` body."""
        before = len(stmts)
        consumed = super()._process_loop(
            instr, instructions, idx, code, stack, stmts, limit=limit
        )
        if len(stmts) == before or not isinstance(stmts[-1], ast.For):
            return consumed
        end_idx = idx + consumed
        if end_idx - 1 > idx and instructions[end_idx - 1].opname == "POP_TOP":
            if instructions[end_idx - 1].is_jump_target:
                stmts[-1].body.append(ast.Break())
                return consumed
        tail = self._find_duplicated_tail(instructions, idx, end_idx)
        if tail is not None and tail - 1 > idx:
            if instructions[tail - 1].opname == "POP_TOP":
                stmts[-1].body.append(ast.Break())
        return consumed

    def _chain_epilogue_confirms(
        self, instructions, epilogue: int, merge: int, end: int
    ) -> bool:
        """Validate the ``POP_TOP`` epilogue of a failing chained-comparison link.

        3.9 leaves an explicit ``JUMP`` after the epilogue that targets the
        merge point.  3.10 drops it: the epilogue simply falls through into the
        shared tail, which the optimizer is free to have duplicated, so the
        following instruction need not be the merge.
        """
        if epilogue + 1 >= end:
            return False
        following = instructions[epilogue + 1]
        if following.opname in _JUMP_OPS:
            return self._jump_target(following) == merge
        return True

    def _parse_chained_term(
        self,
        code,
        instructions,
        start: int,
        marker: int,
        end: int,
        stack,
    ) -> Optional[Tuple[Any, int, int]]:
        """Parse ``a op b op c`` on the 3.10 layout, then fall back to 3.9.

        Mirrors the stock parser; only the epilogue validation differs, because
        3.10 no longer emits the ``JUMP`` that 3.9 used to prove the link
        belonged to the same chain.
        """
        vals = self._eval_ifexp_expr(code, instructions, start, marker, stack)
        if vals is None or len(vals) != len(stack) + 2:
            return None
        left, mid = vals[-2], vals[-1]
        first_guard = marker + 3
        if first_guard >= end or instructions[first_guard].opname not in _POP_JUMPS:
            return None
        ops: List[ast.cmpop] = [self._compare_op(instructions[marker + 2])]
        comparators: List[ast.expr] = [mid]
        cur: List[ast.expr] = [mid]
        link_guards: List[int] = [first_guard]
        guard = first_guard
        i = first_guard + 1
        while True:
            j = i
            link: Optional[int] = None
            while j < end:
                op = instructions[j].opname
                if op == "COMPARE_OP":
                    break
                if (
                    op == "DUP_TOP"
                    and j + 2 < end
                    and instructions[j + 1].opname == "ROT_THREE"
                    and instructions[j + 2].opname == "COMPARE_OP"
                ):
                    link = j
                    break
                if op not in self._IFEXP_EXPR_OPS:
                    return None
                j += 1
            if j >= end:
                return None
            rhs = self._eval_ifexp_expr(code, instructions, i, j, cur)
            if rhs is None or len(rhs) != len(cur) + 1:
                return None
            if link is None:
                compare, guard = j, j + 1
            else:
                compare, guard = j + 2, j + 3
            if guard >= end or instructions[guard].opname not in _POP_JUMPS:
                return None
            comparators.append(rhs[-1])
            ops.append(self._compare_op(instructions[compare]))
            cur = [rhs[-1]]
            link_guards.append(guard)
            i = guard + 1
            if link is None:
                break
        expr = ast.Compare(left=left, ops=ops, comparators=comparators)
        if instructions[guard].opname == "POP_JUMP_IF_TRUE":
            expr = ast.UnaryOp(op=ast.Not(), operand=expr)
        merge = self._jump_target(instructions[guard])
        for link_guard in link_guards[:-1]:
            epilogue = self._find_target_idx(
                instructions, self._jump_target(instructions[link_guard])
            )
            if epilogue < guard + 1 or instructions[epilogue].opname != "POP_TOP":
                return None
            if not self._chain_epilogue_confirms(instructions, epilogue, merge, end):
                return None
        return expr, guard, merge


def decompiler_for(version: str):
    """Return the decompiler class suited to *version*."""
    if version == "3.10":
        return Decompiler310
    if version in ("3.11", "3.12", "3.13", "3.14"):
        from . import decomp311
        return decomp311.Decompiler311
    return _BaseDecompiler


def make_decompiler(version: str):
    """Instantiate the decompiler suited to ``version``."""
    return decompiler_for(version)()
