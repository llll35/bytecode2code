"""Read structural patterns before their stack shuffles become expressions."""
import ast
import dis


class _NoMatch(Exception):
    pass


class _PatternSlot:
    """A subject or extracted field whose binding may be delayed by shuffles."""
    def __init__(self, star=False):
        self.star = star
        self.node = None
        self.kind = None
        self.parts = None
        self.alias = None
        self.cls = None
        self.attrs = ()
        self.positional = 0
        self.keys = ()
        self.rest = None
        self.length = None
        self.length_op = None

    def bind(self, name):
        if self.node is None and self.kind is None:
            self.node = ast.MatchStar(name=name) if self.star else ast.MatchAs(name=name)
        elif name is not None:
            if self.alias is not None or self.star:
                raise _NoMatch()
            self.alias = name

    def render(self):
        node = self.node
        if self.kind is not None:
            if self.parts is None:
                raise _NoMatch()
            parts = [part.render() for part in self.parts]
            if self.kind == 'sequence':
                node = ast.MatchSequence(patterns=parts)
            elif self.kind == 'class':
                node = ast.MatchClass(cls=self.cls, patterns=parts[:self.positional],
                                      kwd_attrs=list(self.attrs), kwd_patterns=parts[self.positional:])
            elif self.kind == 'mapping':
                rest = None
                if self.rest is not None:
                    if self.rest.name is None or tuple(self.rest.deleted) != tuple(self.keys):
                        raise _NoMatch()
                    rest = self.rest.name
                node = ast.MatchMapping(keys=[ast.Constant(value=key) for key in self.keys],
                                        patterns=parts, rest=rest)
        if node is None:
            raise _NoMatch()
        return ast.MatchAs(pattern=node, name=self.alias) if self.alias is not None else node


class _PatternFields:
    def __init__(self, parts):
        self.parts = parts


class _PatternRest:
    def __init__(self, parent=None):
        self.parent = parent
        self.deleted = []
        self.name = None


class PatternReader:
    def __init__(self, decompiler, code, instructions, start, limit):
        self.decompiler = decompiler
        self.code = code
        self.instructions = instructions
        self.start = start
        self.limit = limit
        self.raw = []
        for ins in dis.get_instructions(code):
            if ins.opname in ('CACHE', 'RESUME', 'NOT_TAKEN', 'TO_BOOL', 'EXTENDED_ARG'):
                continue
            if ins.opname in ('STORE_FAST_STORE_FAST', 'STORE_FAST_LOAD_FAST',
                              'LOAD_FAST_LOAD_FAST', 'LOAD_FAST_BORROW_LOAD_FAST_BORROW'):
                kinds = ('STORE_FAST', 'STORE_FAST') if ins.opname == 'STORE_FAST_STORE_FAST' else (
                    ('STORE_FAST', 'LOAD_FAST') if ins.opname == 'STORE_FAST_LOAD_FAST' else
                    ('LOAD_FAST', 'LOAD_FAST'))
                for kind, name in zip(kinds, ins.argval):
                    self.raw.append(ins._replace(opname=kind, argval=name))
            else:
                self.raw.append(ins)
        self.lines = []
        line = None
        for ins in self.raw:
            position = getattr(ins, 'positions', None)
            current = getattr(position, 'lineno', None)
            if current is None:
                current = ins.starts_line
                if isinstance(current, bool):
                    current = None
            line = current or line
            self.lines.append(line)
        self.by_offset = {}
        for i, ins in enumerate(self.raw):
            self.by_offset.setdefault(ins.offset, i)
        self.end = len(self.raw)
        if limit < len(instructions):
            self.end = self.by_offset.get(instructions[limit].offset, self.end)

    def op(self, index):
        return self.raw[index].opname if 0 <= index < self.end else ''

    def target(self, index):
        target = self.by_offset.get(self.raw[index].argval)
        if target is None or target <= index:
            raise _NoMatch()
        return target

    def translated(self, index):
        if index >= len(self.raw):
            return self.limit
        ins = self.raw[index]
        if (self.by_offset[ins.offset] != index
                or index + 1 < len(self.raw) and self.raw[index + 1].offset == ins.offset):
            name = 'LOAD_FAST' if ins.opname.startswith('LOAD_FAST') else ins.opname
            for at, translated in enumerate(self.instructions):
                if translated.offset == ins.offset and translated.opname == name and translated.argval == ins.argval:
                    return at
        return self.decompiler._find_target_idx(self.instructions, self.raw[index].offset)

    def constant(self, index):
        if self.op(index) not in ('LOAD_CONST', 'LOAD_SMALL_INT', 'LOAD_COMMON_CONSTANT'):
            raise _NoMatch()
        return self.raw[index].argval

    def value(self, index):
        op = self.op(index)
        if op in ('LOAD_CONST', 'LOAD_SMALL_INT', 'LOAD_COMMON_CONSTANT'):
            value = ast.Constant(value=self.raw[index].argval)
        elif op.startswith('LOAD_') and op in (
                'LOAD_GLOBAL', 'LOAD_NAME', 'LOAD_FAST', 'LOAD_FAST_BORROW', 'LOAD_DEREF'):
            value = ast.Name(id=str(self.raw[index].argval), ctx=ast.Load())
        else:
            raise _NoMatch()
        index += 1
        while self.op(index) == 'LOAD_ATTR':
            value = ast.Attribute(value=value, attr=str(self.raw[index].argval), ctx=ast.Load())
            index += 1
        return value, index

    def test(self, index, failures):
        if self.op(index) == 'COPY' and self.raw[index].arg == 1:
            index += 1
        if not self.op(index).startswith('POP_JUMP'):
            raise _NoMatch()
        if not self.op(index).endswith(('IF_FALSE', 'IF_NONE', 'IF_NOT_NONE')):
            raise _NoMatch()
        failures.append(self.target(index))
        return index + 1

    def length_test(self, index, failures):
        if self.op(index) != 'GET_LEN':
            raise _NoMatch()
        size = self.constant(index + 1)
        if not isinstance(size, int) or self.op(index + 2) != 'COMPARE_OP':
            raise _NoMatch()
        return size, self.test(index + 3, failures)

    def pattern(self, index, line):
        """Follow the success stack while recording every tested failure edge.

        Captures are often stored only after nested tests and several rotations;
        treating the unpack as a consecutive STORE run binds the wrong field.
        Slots keep their identity through COPY/SWAP/ROT and mapping-rest cleanup.
        """
        while self.op(index) in ('COPY', 'DUP_TOP'):
            index += 1
        root = _PatternSlot()
        stack, failures = [root], []
        while index < self.end and stack:
            op = self.op(index)
            if op == 'MATCH_SEQUENCE' and isinstance(stack[-1], _PatternSlot):
                slot = stack[-1]
                if slot.kind is not None or slot.node is not None:
                    raise _NoMatch()
                slot.kind = 'sequence'
                index = self.test(index + 1, failures)
                if self.op(index) == 'GET_LEN':
                    slot.length = self.constant(index + 1)
                    slot.length_op = self.raw[index + 2].argval
                    _, index = self.length_test(index, failures)
                    if slot.length == 0 and slot.length_op == '==':
                        slot.parts = []
                continue
            if op == 'MATCH_MAPPING' and isinstance(stack[-1], _PatternSlot):
                slot = stack[-1]
                if slot.kind is not None or slot.node is not None:
                    raise _NoMatch()
                slot.kind, slot.parts = 'mapping', []
                index = self.test(index + 1, failures)
                if self.op(index) == 'GET_LEN':
                    size, index = self.length_test(index, failures)
                    keys = self.constant(index)
                    if not isinstance(keys, tuple) or size != len(keys) or self.op(index + 1) != 'MATCH_KEYS':
                        raise _NoMatch()
                    slot.keys, slot.parts = keys, [_PatternSlot() for _ in keys]
                    stack.extend((keys, _PatternFields(slot.parts)))
                    index = self.test(index + 2, failures)
                continue
            if op in ('UNPACK_SEQUENCE', 'UNPACK_EX'):
                unpack = self.raw[index]
                before = unpack.arg & 255
                count = before + (unpack.arg >> 8) + 1 if op == 'UNPACK_EX' else unpack.arg
                value = stack.pop()
                if isinstance(value, _PatternSlot) and value.kind == 'sequence':
                    expected = count - 1 if op == 'UNPACK_EX' else count
                    if value.length is not None and (value.length != expected or
                            value.length_op != ('>=' if op == 'UNPACK_EX' else '==')):
                        raise _NoMatch()
                    value.parts = [_PatternSlot(star=op == 'UNPACK_EX' and i == before) for i in range(count)]
                    parts = value.parts
                elif isinstance(value, _PatternFields) and op == 'UNPACK_SEQUENCE' and len(value.parts) == count:
                    parts = value.parts
                elif isinstance(value, tuple) and op == 'UNPACK_SEQUENCE' and len(value) == count:
                    parts = value
                else:
                    raise _NoMatch()
                stack.extend(reversed(parts))
                index += 1
                continue
            if op in ('COPY', 'DUP_TOP'):
                distance = self.raw[index].arg if op == 'COPY' else 1
                if not distance or distance > len(stack):
                    raise _NoMatch()
                stack.append(stack[-distance])
            elif op == 'SWAP' or op in ('ROT_TWO', 'ROT_THREE', 'ROT_FOUR', 'ROT_N'):
                distance = self.raw[index].arg if op in ('SWAP', 'ROT_N') else {
                    'ROT_TWO': 2, 'ROT_THREE': 3, 'ROT_FOUR': 4}[op]
                if not distance or distance > len(stack):
                    raise _NoMatch()
                if op == 'SWAP':
                    stack[-1], stack[-distance] = stack[-distance], stack[-1]
                else:
                    stack[-distance:] = [stack[-1]] + stack[-distance:-1]
            elif op == 'POP_TOP':
                value = stack.pop()
                if isinstance(value, _PatternSlot):
                    value.bind(None)
            elif op in ('STORE_FAST', 'STORE_NAME', 'STORE_DEREF', 'STORE_GLOBAL'):
                value, name = stack.pop(), str(self.raw[index].argval)
                if isinstance(value, _PatternSlot):
                    value.bind(name)
                elif isinstance(value, _PatternRest) and value.parent is not None:
                    value.name = name
                else:
                    raise _NoMatch()
            elif op == 'BUILD_MAP' and self.raw[index].arg == 0:
                stack.append(_PatternRest())
            elif op == 'DICT_UPDATE':
                parent = stack.pop()
                distance = self.raw[index].arg
                if not distance or distance > len(stack) or not isinstance(parent, _PatternSlot) or parent.kind != 'mapping':
                    raise _NoMatch()
                rest = stack[-distance]
                if not isinstance(rest, _PatternRest) or rest.parent is not None:
                    raise _NoMatch()
                rest.parent, parent.rest = parent, rest
            elif op == 'DELETE_SUBSCR':
                key, rest = stack.pop(), stack.pop()
                if not isinstance(rest, _PatternRest) or rest.parent is None or key not in rest.parent.keys:
                    raise _NoMatch()
                rest.deleted.append(key)
            elif op == 'COPY_DICT_WITHOUT_KEYS':
                keys = stack.pop()
                parent = stack[-1]
                if not isinstance(parent, _PatternSlot) or parent.kind != 'mapping' or keys != parent.keys:
                    raise _NoMatch()
                rest = _PatternRest(parent)
                rest.deleted = list(keys)
                parent.rest = rest
                stack.append(rest)
            elif op.startswith('POP_JUMP') and op.endswith('IF_NOT_NONE') and isinstance(stack[-1], _PatternSlot):
                slot = stack.pop()
                if slot.kind is not None or slot.node is not None:
                    raise _NoMatch()
                slot.node = ast.MatchSingleton(value=None)
                index = self.test(index, failures)
                continue
            elif op.startswith('LOAD_'):
                value, after = self.value(index)
                if self.op(after) == 'BINARY_SUBSCR' and isinstance(stack[-1], _PatternFields):
                    if not isinstance(value, ast.Constant) or not isinstance(value.value, int):
                        raise _NoMatch()
                    fields = stack.pop()
                    if not 0 <= value.value < len(fields.parts):
                        raise _NoMatch()
                    stack.append(fields.parts[value.value])
                    index = after + 1
                    continue
                if (self.op(after) == 'LOAD_CONST' and isinstance(self.raw[after].argval, tuple)
                        and self.op(after + 1) == 'MATCH_CLASS' and isinstance(stack[-1], _PatternSlot)):
                    slot = stack.pop()
                    if slot.kind is not None or slot.node is not None:
                        raise _NoMatch()
                    slot.kind, slot.cls = 'class', value
                    slot.attrs, slot.positional = self.raw[after].argval, self.raw[after + 1].arg
                    slot.parts = [_PatternSlot() for _ in range(slot.positional + len(slot.attrs))]
                    stack.append(_PatternFields(slot.parts))
                    index = self.test(after + 2, failures)
                    continue
                if (self.op(after) in ('COMPARE_OP', 'IS_OP') and isinstance(stack[-1], _PatternSlot)
                        and (self.op(after) == 'IS_OP' or self.raw[after].argval == '==')):
                    slot = stack.pop()
                    if slot.kind is not None or slot.node is not None:
                        raise _NoMatch()
                    slot.node = (ast.MatchSingleton(value=value.value) if isinstance(value, ast.Constant)
                                 and (value.value is None or isinstance(value.value, bool))
                                 else ast.MatchValue(value=value))
                    index = self.test(after + 1, failures)
                    continue
                break
            else:
                break
            index += 1
        return root.render(), index, failures

    def failure(self, index, line):
        seen = set()
        while index < self.end and index not in seen:
            seen.add(index)
            if self.op(index) == 'POP_TOP' and self.lines[index] == line:
                index += 1
            elif self.op(index) in ('JUMP_FORWARD', 'JUMP_ABSOLUTE') and self.lines[index] == line:
                index = self.target(index)
            else:
                return index
        raise _NoMatch()

    def success(self, index, line, pattern_failures=()):
        alias, guard, failures = None, None, []
        seen = set()
        while index < self.end and index not in seen:
            seen.add(index)
            op = self.op(index)
            if op == 'POP_TOP':
                index += 1
            elif op in ('JUMP_FORWARD', 'JUMP_ABSOLUTE'):
                if self.lines[index] != line:
                    return index, alias, guard, failures
                index = self.target(index)
            elif op.startswith('STORE_') and self.lines[index] == line:
                if alias is not None:
                    raise _NoMatch()
                alias = str(self.raw[index].argval)
                index += 1
            else:
                if guard is not None:
                    return index, alias, guard, failures
                try:
                    guard, after, failed = self.guard(index, line, pattern_failures)
                except _NoMatch:
                    return index, alias, None, failures
                index = after
                failures.extend(failed)
        raise _NoMatch()

    def guard(self, index, line, pattern_failures=()):
        """Read the guard's forward decision graph, not a same-line jump list.

        Internal targets distinguish ``a and (b or c)`` from a flat chain.
        Every external false edge must reach the next case, including when
        the compiler uses several differently sized pattern cleanup stubs.
        """
        end = index
        stops = {'POP_TOP', 'RETURN_VALUE', 'RETURN_CONST', 'RAISE_VARARGS',
                 'RERAISE', 'NOP', 'JUMP_FORWARD', 'JUMP_ABSOLUTE',
                 'JUMP_BACKWARD', 'FOR_ITER', 'STORE_ATTR', 'STORE_SUBSCR',
                 'YIELD_VALUE', 'PUSH_EXC_INFO', 'POP_EXCEPT', 'MATCH_SEQUENCE',
                 'MATCH_MAPPING', 'MATCH_CLASS', 'MATCH_KEYS'}
        while end < self.end and self.op(end) not in stops:
            if self.op(end).startswith('STORE_'):
                break
            end += 1
        branches = [i for i in range(index, end)
                    if self.op(i).startswith('POP_JUMP') and self.op(i).endswith(('IF_FALSE', 'IF_TRUE'))]
        if not branches or len(branches) > 64:
            raise _NoMatch()
        following = {self.failure(failure, line) for failure in pattern_failures}
        if len(following) > 1:
            raise _NoMatch()
        expected = next(iter(following), None)
        starts, operands, targets = [], [], []
        for branch in branches:
            operand = self.decompiler._eval_value_operand(
                self.code, self.instructions, self.translated(index), self.translated(branch), [])
            if operand is None or len(operand) != 1:
                break
            starts.append(index)
            operands.append(operand[0])
            targets.append(self.target(branch))
            index = branch + 1
        for count in range(len(operands), 0, -1):
            body = branches[count - 1] + 1
            clean = body
            while self.op(clean) == 'POP_TOP':
                clean += 1
            failure = self.failure(targets[count - 1], line)
            if expected is not None and failure != expected:
                continue
            by_start = {at: i for i, at in enumerate(starts[:count])}
            edges, failed = [], []
            for i, target in enumerate(targets[:count]):
                if target in by_start:
                    taken = by_start[target]
                elif body <= target <= clean:
                    taken = count
                elif target > body and self.failure(target, line) == failure:
                    taken = count + 1
                    failed.append(target)
                else:
                    break
                ordinary = i + 1
                edges.append((taken, ordinary) if self.op(branches[i]).endswith('IF_TRUE')
                             else (ordinary, taken))
            if len(edges) != count:
                continue
            result = self.boolean(operands[:count], edges)
            if result is not None:
                return result, body, failed
        raise _NoMatch()

    @staticmethod
    def boolean(operands, edges):
        """Factor a short-circuit graph without duplicating any truth test."""
        cache = {}

        def join(kind, left, right):
            values = []
            for value in (left, right):
                if isinstance(value, ast.BoolOp) and isinstance(value.op, kind):
                    values.extend(value.values)
                else:
                    values.append(value)
            return ast.BoolOp(op=kind(), values=values)

        def build(start, end, yes, no):
            key = start, end, yes, no
            if key in cache:
                return cache[key]
            cache[key] = None
            if any(target not in (yes, no) and not start <= target < end
                   for edge in edges[start:end] for target in edge):
                return None
            if end == start + 1:
                if edges[start] == (yes, no):
                    cache[key] = operands[start]
                elif edges[start] == (no, yes):
                    cache[key] = ast.UnaryOp(op=ast.Not(), operand=operands[start])
                return cache[key]
            for middle in range(start + 1, end):
                for kind, left_yes, left_no in ((ast.And, middle, no), (ast.Or, yes, middle)):
                    left = build(start, middle, left_yes, left_no)
                    if left is None:
                        continue
                    right = build(middle, end, yes, no)
                    if right is not None:
                        cache[key] = join(kind, left, right)
                        return cache[key]
            return None

        return build(0, len(operands), len(operands), len(operands) + 1)

    def body(self, start, end):
        keep = self.decompiler._keep_clause_returns
        try:
            if self.op(start) in ('LOAD_CONST', 'LOAD_COMMON_CONSTANT', 'RETURN_CONST') and self.raw[start].argval is None:
                self.decompiler._keep_clause_returns = True
            result = self.decompiler._emit_statements(
                self.code, self.instructions, start=self.translated(start),
                end=min(self.limit, self.translated(end)))
        finally:
            self.decompiler._keep_clause_returns = keep
        return result or [ast.Pass()]

    def read(self):
        first = self.by_offset.get(self.instructions[self.start].offset)
        if first is None or self.lines[first] is None:
            raise _NoMatch()
        # A fused store/load has two entries at the same byte offset.
        original = self.instructions[self.start]
        while (first + 1 < self.end and self.raw[first + 1].offset == original.offset
               and self.raw[first].argval != original.argval):
            first += 1
        subject_position = getattr(self.raw[first], 'positions', None)
        expression_ops = self.decompiler._IFEXP_EXPR_OPS | self.decompiler._VALUE_GUARD_OPS
        for pattern_start in range(first + 1, self.end):
            position = getattr(self.raw[pattern_start], 'positions', None)
            later = self.lines[pattern_start] is not None and self.lines[pattern_start] > self.lines[first]
            inside = (subject_position is None or position is None
                      or subject_position.col_offset is None or position.col_offset is None
                      or position.col_offset >= subject_position.col_offset)
            if later and inside:
                with self.decompiler._isolated_state():
                    subject = self.decompiler._eval_value_operand(
                        self.code, self.instructions, self.start, self.translated(pattern_start), [])
                    if subject is not None and len(subject) == 1:
                        try:
                            return self.read_cases(pattern_start, subject[0])
                        except _NoMatch:
                            pass
            at = self.translated(pattern_start)
            if at >= self.limit or self.instructions[at].opname not in expression_ops:
                break  # Never search across a statement for a nicer-looking subject.
        raise _NoMatch()

    def read_cases(self, pattern_start, subject):
        cases, index, match_end = [], pattern_start, self.end
        while index < match_end:
            line = self.lines[index]
            if self.op(index) == 'NOP':
                if not cases:
                    raise _NoMatch()
                position = getattr(self.raw[index], 'positions', None)
                if (self.op(index) == 'NOP' and position is not None and position.col_offset is not None
                        and position.end_col_offset - position.col_offset != 1):
                    raise _NoMatch()
                cases.append(ast.match_case(pattern=ast.MatchAs(), guard=None,
                                            body=self.body(index + 1, match_end)))
                index = match_end
                break
            alternatives, successes, failures = [], [], []
            pending, seen = [index], set()
            next_cases = set()
            while pending:
                at = pending.pop()
                if at in seen:
                    continue
                seen.add(at)
                pattern, success, failed = self.pattern(at, line)
                body, alias, guard, guard_failures = self.success(success, line, failed)
                if not failed and not guard_failures:
                    if not cases or alternatives:
                        raise _NoMatch()
                    cases.append(ast.match_case(pattern=pattern, guard=guard, body=self.body(body, match_end)))
                    return ast.Match(subject=subject, cases=cases), self.translated(match_end)
                alternatives.append(pattern)
                successes.append((body, alias, guard))
                failures.extend(failed + guard_failures)
                for failure in failed + guard_failures:
                    following = self.failure(failure, line)
                    epilogue = (self.op(following) in ('RETURN_CONST', 'LOAD_CONST', 'LOAD_COMMON_CONSTANT')
                                and self.raw[following].argval is None)
                    if following < self.end and self.lines[following] == line and self.op(following) != 'NOP' and not epilogue:
                        pending.append(following)
                    else:
                        next_cases.add(following)
            if len(next_cases) != 1 or not alternatives:
                raise _NoMatch()
            following = next_cases.pop()
            if following <= index:
                raise _NoMatch()
            body_start, alias, guard = successes[0]
            if any(other_alias != alias or ast.dump(other_guard or ast.Constant(value=None)) !=
                   ast.dump(guard or ast.Constant(value=None)) for _, other_alias, other_guard in successes):
                raise _NoMatch()
            pattern = alternatives[0] if len(alternatives) == 1 else ast.MatchOr(patterns=alternatives)
            if alias is not None:
                pattern = ast.MatchAs(pattern=pattern, name=alias)
            body_end = min([f for f in failures if f > body_start] + [following, match_end])
            if (body_end > body_start and self.op(body_end - 1) in ('JUMP_FORWARD', 'JUMP_ABSOLUTE')
                    and self.raw[body_end - 1].argval > self.raw[body_end - 1].offset
                    and self.decompiler._classify_jump(
                        self.instructions, self.instructions[self.translated(body_end - 1)]) is None):
                target = self.target(body_end - 1)
                if target >= following:
                    match_end = min(match_end, target)
                    body_end -= 1
            cases.append(ast.match_case(pattern=pattern, guard=guard, body=self.body(body_start, body_end)))
            index = following
            if index >= match_end:
                break
            if (self.op(index) in ('RETURN_CONST', 'LOAD_CONST', 'LOAD_COMMON_CONSTANT')
                    and self.raw[index].argval is None and self.lines[index] <= line):
                break  # implicit no-match epilogue, not a wildcard case
            if self.lines[index] is None or self.lines[index] <= line:
                raise _NoMatch()
        if not cases:
            raise _NoMatch()
        return ast.Match(subject=subject, cases=cases), self.translated(index)


def read_match(decompiler, code, instructions, start, limit):
    """Return a match node and its continuation only for a complete pattern run."""
    try:
        node, after = PatternReader(decompiler, code, instructions, start, limit).read()
        return (node, after) if start < after <= limit else None
    except (_NoMatch, IndexError):
        return None
