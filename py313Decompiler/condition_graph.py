"""Recover mixed Boolean tests without duplicating truth evaluations."""
import ast

_GUARDS = ('POP_JUMP_IF_FALSE', 'POP_JUMP_IF_TRUE')
_JUMPS = ('JUMP_ABSOLUTE', 'JUMP_FORWARD')
_LOADS = ('LOAD_FAST', 'LOAD_NAME', 'LOAD_GLOBAL', 'LOAD_DEREF', 'LOAD_CONST')


def _line(instructions, index):
    while index >= 0:
        instruction = instructions[index]
        line = getattr(getattr(instruction, 'positions', None), 'lineno', None)
        if line is None:
            line = instruction.line_no
        if line is not None:
            return line
        index -= 1
    return None


def _factor(operands, edges):
    from .pattern_match import PatternReader
    return PatternReader.boolean(operands, edges)


def read_condition(decompiler, code, instructions, start, end, stack=(),
                   success_offset=None, failure_offset=None):
    """Return the complete same-header decision graph, or decline the shape.

    Existing readers still handle flat chains, value expressions and multiline
    conditions. This reader cannot cross a statement into its body's own test.
    Explicit endpoints also recognise the compiler's repeated while footer.
    """
    if start >= end or instructions[start].opname not in _LOADS:
        return None
    header_line = _line(instructions, start)
    if header_line is None:
        return None
    starts, guards, operands = [], [], []
    index = start
    while index < end and len(guards) < 64:
        guard = decompiler._find_ifexp_condition_jump(instructions, index, end, allow_namedexpr=True)
        if (guard is None or instructions[guard].opname not in _GUARDS
                or _line(instructions, guard) != header_line):
            break
        values = decompiler._eval_ifexp_expr(code, instructions, index, guard, list(stack))
        if not decompiler._is_ifexp_value_stack(values, stack):
            break
        starts.append(index)
        guards.append(guard)
        operands.append(values[-1])
        index = guard + 1
        # 3.12/3.13 spell a successful footer edge as a pop-jump followed by
        # JUMP_ABSOLUTE to the body, then park another operand behind it.
        if (success_offset is not None and index < end
                and instructions[index].opname in _JUMPS
                and decompiler._jump_target(instructions[index]) in (success_offset, failure_offset)):
            index += 1
    for count in range(len(guards), 1, -1):
        last = guards[count - 1]
        if last + 1 >= len(instructions):
            continue
        body, branch = last + 1, last
        yes = instructions[body].offset if success_offset is None else success_offset
        no = decompiler._jump_target(instructions[last]) if failure_offset is None else failure_offset
        if (success_offset is None and instructions[last].opname == 'POP_JUMP_IF_TRUE'
                and last + 2 < len(instructions) and instructions[last + 1].opname in _JUMPS
                and decompiler._jump_target(instructions[last]) == instructions[last + 2].offset):
            body = branch = last + 1
            body += 1
            yes = instructions[body].offset
            no = decompiler._jump_target(instructions[branch])
        by_offset = {instructions[at].offset: i for i, at in enumerate(starts[:count])}

        def route(offset):
            seen = set()
            for _ in range(8):
                if offset == yes:
                    return count
                if offset == no:
                    return count + 1
                if offset in by_offset:
                    return by_offset[offset]
                if offset in seen or offset is None:
                    return None
                seen.add(offset)
                at = decompiler._find_target_idx(instructions, offset)
                if at >= len(instructions) or instructions[at].opname not in _JUMPS:
                    return None
                offset = decompiler._jump_target(instructions[at])
            return None

        edges, destinations = [], []
        for i, guard in enumerate(guards[:count]):
            taken = route(decompiler._jump_target(instructions[guard]))
            ordinary = (i + 1 if i + 1 < count and guard + 1 == starts[i + 1]
                        else route(instructions[guard + 1].offset))
            if taken is None or ordinary is None:
                break
            destinations.append(taken)
            edges.append((taken, ordinary) if instructions[guard].opname == 'POP_JUMP_IF_TRUE'
                         else (ordinary, taken))
        if len(edges) != count:
            continue
        mixed = (any(target < count for target in destinations)
                 or len(set(destinations[:-1])) > 1)
        test = _factor(operands[:count], edges)
        if test is not None:
            return {'test': test, 'branch': branch, 'body': body, 'failure': no,
                    'last': last, 'mixed': mixed, 'line': header_line}
    return None


def emit_mixed_if(decompiler, code, instructions, start, end, stack, statements):
    parsed = read_condition(decompiler, code, instructions, start, end, stack)
    if parsed is None or not parsed['mixed']:
        return 0
    branch = parsed['branch']
    consumed = decompiler._emit_conditional(parsed['test'], instructions, branch, code,
                                           stack, statements, parsed['failure'], end)
    return max(0, branch + consumed - start)


def emit_threaded_break(decompiler, condition, instructions, index, statements, limit):
    """Recover a taken break stub parked after the loop's natural latch."""
    stop = len(instructions) if limit is None else limit
    if not decompiler._loop_stack or index + 1 >= stop:
        return 0
    latch = instructions[index + 1]
    target = decompiler._jump_target(instructions[index])
    if (latch.opname not in _JUMPS or target is None
            or _line(instructions, index + 1) != _line(instructions, index)
            or not isinstance(decompiler._classify_jump(instructions, latch), ast.Continue)):
        return 0
    stub = decompiler._find_target_idx(instructions, target)
    if not index + 1 < stub < stop or instructions[stub].opname not in _JUMPS:
        return 0
    if not isinstance(decompiler._classify_jump(instructions, instructions[stub]), ast.Break):
        return 0
    test = condition.operand if isinstance(condition, ast.UnaryOp) and isinstance(condition.op, ast.Not) else (
        ast.UnaryOp(op=ast.Not(), operand=condition))
    statements.append(ast.If(test=test, body=[ast.Break()], orelse=[]))
    return stub + 1 - index


def emit_mixed_while(decompiler, code, instructions, start, end, statements):
    if start >= end or instructions[start].offset in decompiler._loop_heads:
        return 0
    parsed = read_condition(decompiler, code, instructions, start, end)
    if parsed is None or not parsed['mixed']:
        return 0
    head, body = instructions[start].offset, parsed['body']
    failure = decompiler._find_target_idx(instructions, parsed['failure'])
    if not body < failure <= end:
        return 0
    # 3.9 and 3.14+ jump to the condition itself; use the last natural latch,
    # not an earlier explicit continue in the same body.
    backs = [i for i in range(body, failure)
             if instructions[i].opname in _JUMPS and decompiler._jump_target(instructions[i]) == head]
    if backs:
        body_end = back = backs[-1]
        stub_end = back + 1
        while (stub_end < failure and instructions[stub_end].opname in _JUMPS
               and decompiler._jump_target(instructions[stub_end]) >= parsed['failure']):
            stub_end += 1
        if stub_end > back + 1:
            body_end = stub_end
    else:
        # 3.10--3.13 repeat the condition and jump to the body. A matching AST
        # and source header prove ownership; a nested loop's latch is not enough.
        body_end = back = None
        for at in range(body, failure):
            if instructions[at].opname not in _LOADS or _line(instructions, at) != parsed['line']:
                continue
            footer = read_condition(decompiler, code, instructions, at, failure,
                                    success_offset=instructions[body].offset,
                                    failure_offset=parsed['failure'])
            if footer is not None and ast.dump(footer['test']) == ast.dump(parsed['test']):
                body_end, back = at, footer['last']
                break
        if body_end is None:
            return 0
    exits = [decompiler._find_target_idx(instructions, decompiler._jump_target(instructions[i]))
             for i in range(body, failure) if instructions[i].opname in _JUMPS
             and decompiler._jump_target(instructions[i]) >= parsed['failure']]
    after = max([failure] + exits)
    if after > end:
        return 0
    exit_offset = instructions[after].offset if after < len(instructions) else instructions[-1].offset + 2
    body_statements = decompiler._emit_loop_body(code, instructions, body, body_end, head, exit_offset)
    other = decompiler._emit_statements(code, instructions, start=failure, end=after) if failure < after else []
    statements.append(ast.While(test=parsed['test'], body=body_statements, orelse=other))
    return after - start


def _return_column(instructions, index):
    position = getattr(instructions[index], 'positions', None)
    column = getattr(position, 'col_offset', None)
    if column is not None and index:
        previous = instructions[index - 1]
        # Rewriter._make already rebases the same-offset RETURN_CONST pair.
        if (previous.opname == 'LOAD_CONST' and previous.argval is not None
                and previous.offset != instructions[index].offset
                and getattr(previous, 'positions', None) == position):
            column -= 7  # RETURN_CONST/value-position return: account for "return ".
    return column


def returns_are_statements(instructions, guard, end):
    """Reject IfExp recovery when a true arm contains a source-level return."""
    position = getattr(instructions[guard], 'positions', None)
    line, column = getattr(position, 'lineno', None), getattr(position, 'col_offset', None)
    if line is None or column is None:
        return False
    for index in range(guard + 1, end):
        if instructions[index].opname not in ('RETURN_VALUE', 'RETURN_CONST'):
            continue
        returned = getattr(instructions[index], 'positions', None)
        returned_line = getattr(returned, 'lineno', None)
        returned_column = _return_column(instructions, index)
        if (returned_line is not None and returned_column is not None
                and returned_line > line and returned_column > column - 3):
            return True
    return False


def returning_elif(decompiler, code, instructions, guard, body_end, start, limit):
    """Read an elif chain that returns before its ordinary merge jump.

    PEP 657 distinguishes the five-column 'elif ' prefix from another 'if '
    or a genuinely nested if. Without those columns this routine declines.
    """
    position = getattr(instructions[guard], 'positions', None)
    column = getattr(position, 'col_offset', None)
    parent_column = _return_column(instructions, body_end - 1) if body_end else None
    if column is None or parent_column is None:
        return None
    chain, cursor = [], start
    while cursor < limit:
        candidate = getattr(instructions[cursor], 'positions', None)
        if getattr(candidate, 'col_offset', None) != column + 2:
            break
        jump = decompiler._find_ifexp_condition_jump(instructions, cursor, limit)
        if jump is None:
            break
        stop = decompiler._find_target_idx(instructions, decompiler._jump_target(instructions[jump]))
        if not jump < stop <= limit or _return_column(instructions, stop - 1) != parent_column:
            break
        nodes = decompiler._emit_statements(code, instructions, start=cursor, end=stop)
        if (len(nodes) != 1 or not isinstance(nodes[0], ast.If) or nodes[0].orelse
                or not nodes[0].body or not isinstance(nodes[0].body[-1], ast.Return)):
            break
        if chain:
            chain[-1].orelse = [nodes[0]]
        chain.append(nodes[0])
        cursor = stop
    return ([chain[0]], cursor) if chain else None
