"""Back-translate CPython 3.11 / 3.12 bytecode into the 3.9 shape.

The project's :class:`bytecode2code.Decompiler` was written against Python
3.9 and keys every decision off ``Instruction.opname``/``argval``.  3.11
renamed half the opcode set and replaced the block stack with a zero cost
exception table, but the *abstract* operations the decompiler emulates are
unchanged.

This module rewrites a 3.11 instruction stream into the equivalent 3.9
stream -- keeping the original byte offsets, so every jump target stays valid
-- and hands the result to the stock decompiler.  The rewriting is purely
syntactic; the decompiler keeps doing all the work.

3.12 needs more than renaming, and each difference is handled where it arises:

* comprehensions are inlined into the enclosing code object rather than called
  as a nested one, so the loop is lifted back into a synthetic ``<listcomp>``
  code object (:meth:`Rewriter._analyse_comprehensions`);
* ``super()`` has its own opcode, so the implicit operands and the call they
  stood for are put back (:meth:`Rewriter._analyse_super`);
* short-circuit operators duplicate the tested value instead of using
  ``JUMP_IF_*_OR_POP`` (:meth:`Rewriter._or_pop_jump`);
* an exception handler that handled the exception jumps *backward* into the
  tail it duplicated, which reads as a loop
  (:meth:`Rewriter._redirect_handler_exits`).
"""
import dis
import sys
import ast
from .disassembler import Instruction
from .decompiler import _is_bare_return

from .decomp_compat import Decompiler310

NB_TO_OPCODE = {
    'NB_ADD': 'BINARY_ADD',
    'NB_SUBTRACT': 'BINARY_SUBTRACT',
    'NB_MULTIPLY': 'BINARY_MULTIPLY',
    'NB_FLOOR_DIVIDE': 'BINARY_FLOOR_DIVIDE',
    'NB_TRUE_DIVIDE': 'BINARY_TRUE_DIVIDE',
    'NB_REMAINDER': 'BINARY_MODULO',
    'NB_POWER': 'BINARY_POWER',
    'NB_LSHIFT': 'BINARY_LSHIFT',
    'NB_RSHIFT': 'BINARY_RSHIFT',
    'NB_AND': 'BINARY_AND',
    'NB_XOR': 'BINARY_XOR',
    'NB_OR': 'BINARY_OR',
    'NB_MATRIX_MULTIPLY': 'BINARY_MATRIX_MULTIPLY',
    'NB_INPLACE_ADD': 'INPLACE_ADD',
    'NB_INPLACE_SUBTRACT': 'INPLACE_SUBTRACT',
    'NB_INPLACE_MULTIPLY': 'INPLACE_MULTIPLY',
    'NB_INPLACE_FLOOR_DIVIDE': 'INPLACE_FLOOR_DIVIDE',
    'NB_INPLACE_TRUE_DIVIDE': 'INPLACE_TRUE_DIVIDE',
    'NB_INPLACE_REMAINDER': 'INPLACE_MODULO',
    'NB_INPLACE_POWER': 'INPLACE_POWER',
    'NB_INPLACE_LSHIFT': 'INPLACE_LSHIFT',
    'NB_INPLACE_RSHIFT': 'INPLACE_RSHIFT',
    'NB_INPLACE_AND': 'INPLACE_AND',
    'NB_INPLACE_XOR': 'INPLACE_XOR',
    'NB_INPLACE_OR': 'INPLACE_OR',
    'NB_INPLACE_MATRIX_MULTIPLY': 'INPLACE_MATRIX_MULTIPLY',
    # 3.14 folded the subscript into ``BINARY_OP`` (oparg name ``[]``), the
    # same way 3.12 folded the two-argument slice; 3.9 spells it
    # ``BINARY_SUBSCR``.
    'NB_SUBSCR': 'BINARY_SUBSCR',
}


def _nb_opcode(arg):
    """Resolve a ``BINARY_OP`` argument through the running interpreter."""
    table = getattr(dis, '_nb_ops', None) or getattr(dis, 'nb_ops', ())
    if arg is None or not 0 <= arg < len(table):
        return 'BINARY_ADD'
    slot = table[arg][0]
    if slot in NB_TO_OPCODE:
        return NB_TO_OPCODE[slot]
    return 'BINARY_ADD'


#: 3.12 turned a handful of one-off opcodes into ``CALL_INTRINSIC_1`` calls.
#: Only the ones with a plain 3.9 opcode behind them are listed; the rest
#: (``ASYNC_GEN_WRAP``, the type-parameter intrinsics) belong to machinery the
#: stock reader already models elsewhere or never meets in source position.
INTRINSIC_1_TO_OPCODE = {
    'INTRINSIC_UNARY_POSITIVE': 'UNARY_POSITIVE',
    'INTRINSIC_LIST_TO_TUPLE': 'LIST_TO_TUPLE',
    'INTRINSIC_IMPORT_STAR': 'IMPORT_STAR',
}


def _intrinsic_1_opcode(arg):
    """Resolve a ``CALL_INTRINSIC_1`` argument, or ``None`` when unmapped."""
    table = getattr(dis, '_intrinsic_1_descs', None)
    if arg is None or not table or not 0 <= arg < len(table):
        return None
    return INTRINSIC_1_TO_OPCODE.get(table[arg])


#: Opcodes that exist only to keep 3.11+'s own bookkeeping on the stack.
DROPPED = frozenset((
    'RESUME', 'CACHE', 'PRECALL', 'MAKE_CELL', 'COPY_FREE_VARS',
    'RETURN_GENERATOR', 'NOT_TAKEN', 'POP_ITER', 'END_FOR', 'KW_NAMES',
    'RETURN_CONST', 'END_SEND', 'SET_FUNCTION_ATTRIBUTE', 'TO_BOOL',
))

#: 3.13 packs two locals into one oparg (high nibble first) and 3.14 borrows
#: the same pairs.  Each is expanded into the two 3.9 loads/stores it stands
#: for before any analysis runs, so the rest of the rewriter only ever sees
#: the plain opcodes.
_FAST_PAIR_OPS = frozenset((
    'LOAD_FAST_LOAD_FAST', 'LOAD_FAST_BORROW_LOAD_FAST_BORROW',
    'STORE_FAST_STORE_FAST', 'STORE_FAST_LOAD_FAST',
))

#: 3.14's ``LOAD_COMMON_CONSTANT`` operands.  Only the ones with a 3.9
#: spelling are listed; the rest are pinned to the constant they load.
_COMMON_CONSTANTS = {
    'AssertionError': 'LOAD_ASSERTION_ERROR',
}

#: 3.14's ``LOAD_COMMON_CONSTANT`` / ``LOAD_SPECIAL`` opargs index tables that
#: only ``dis`` exposes; resolve them to the names the rewriter compares.
def _common_constant(arg):
    table = getattr(dis, '_common_constants', ())
    if arg is not None and 0 <= arg < len(table):
        return table[arg]
    return None


def _special_method(arg):
    table = getattr(dis, '_special_method_names', ())
    if arg is not None and 0 <= arg < len(table):
        return table[arg]
    return None

#: The rotation each ``SWAP`` depth stands for.
SWAP_TO_ROT = {2: 'ROT_TWO', 3: 'ROT_THREE', 4: 'ROT_FOUR'}

#: Opcodes that may sit between the end of a ``with`` body and the implicit
#: ``__exit__`` call: the three ``None`` operands 3.12 pushes for it, and the
#: ``PRECALL`` 3.11 slips in front of the call itself.
_EXIT_OPERANDS = frozenset((
    'SWAP', 'COPY', 'POP_TOP', 'NOP', 'LOAD_CONST', 'LOAD_SMALL_INT',
    'PUSH_NULL', 'PRECALL',
))

#: 3.12 renamed the conditional jumps; the 3.9 spelling is listed here.
POP_JUMP_ALIASES = {
    'POP_JUMP_FORWARD_IF_FALSE': 'POP_JUMP_IF_FALSE',
    'POP_JUMP_BACKWARD_IF_FALSE': 'POP_JUMP_IF_FALSE',
    'POP_JUMP_FORWARD_IF_TRUE': 'POP_JUMP_IF_TRUE',
    'POP_JUMP_BACKWARD_IF_TRUE': 'POP_JUMP_IF_TRUE',
}

#: 3.12 pairs ``LOAD_FAST`` with a checked variant the compiler uses where the
#: slot may be unbound (after a ``del``, in an unreachable branch).  It pushes
#: the same value, and the 3.9 reader only knows the plain spelling.
LOAD_FAST_ALIASES = {
    'LOAD_FAST_CHECK': 'LOAD_FAST',
}

_STORE_OPS = frozenset((
    'STORE_FAST', 'STORE_NAME', 'STORE_DEREF', 'STORE_GLOBAL',
))

_UNPACK_OPS = frozenset((
    'UNPACK_SEQUENCE', 'UNPACK_EX', 'LIST_APPEND', 'SET_ADD', 'MAP_ADD',
))


def _duplicates_for(instr):
    """True when *instr* pushes an extra copy of the value on top of the stack.

    ``a = b = 1`` duplicates the value once per extra target, so a run of
    stores right after one is a chained assignment and not the parallel
    assignment the rotation idiom stands for -- rewriting it swaps the two
    names and turns the source into ``b, a = (1, 1)``.
    """
    if instr.opname == 'DUP_TOP':
        return True
    return instr.opname == 'COPY' and instr.arg == 1

#: Opcodes ``MAKE_FUNCTION`` may consume between the function object it wraps
#: and the ``LOAD_CONST`` that produced it.
_MAKE_OPERANDS = frozenset((
    'LOAD_CONST', 'LOAD_CLOSURE', 'BUILD_TUPLE', 'BUILD_CONST_KEY_MAP',
    'BUILD_MAP', 'BUILD_LIST', 'BUILD_SET', 'DICT_MERGE', 'DICT_UPDATE',
    'LIST_EXTEND', 'SET_UPDATE', 'LOAD_FAST', 'LOAD_NAME', 'LOAD_GLOBAL',
))

#: Opcodes whose low bit is a flag rather than part of the argument, so 3.9
#: spells them with the bit cleared.
_NULL_BIT_OPS = frozenset((
    'LOAD_GLOBAL', 'LOAD_DEREF', 'LOAD_FAST', 'LOAD_FAST_BORROW',
))

#: The ``ROT`` prefix 3.9 put in front of a parallel assignment of *n* names
#: whose values were already on the stack in the target order.  3.11 keeps the
#: same net effect by storing the names in reverse order and no rotation at
#: all, so the shape has to be rebuilt rather than renamed.
ROT_PREFIX = {2: ('ROT_TWO',), 3: ('ROT_THREE', 'ROT_TWO')}

#: Opcodes that end a statement, so a pending method loader can no longer be
#: feeding the next call.
_JUMP_OPS = frozenset((
    'JUMP_ABSOLUTE', 'JUMP_FORWARD', 'JUMP_BACKWARD', 'JUMP',
    'JUMP_BACKWARD_NO_INTERRUPT',
))

#: Opcodes that can appear between the ``super`` lookup and the
#: ``LOAD_SUPER_ATTR`` that consumes it -- i.e. the operands of an explicit
#: ``super(C, self)`` call.
_SUPER_OPERANDS = frozenset((
    'LOAD_GLOBAL', 'LOAD_NAME', 'LOAD_FAST', 'LOAD_DEREF', 'LOAD_FAST_BORROW',
    'LOAD_CLASSDEREF', 'COPY', 'SWAP', 'DUP_TOP', 'BINARY_SUBSCR',
))

#: Opcodes a ``co_exceptiontable`` handler may use while unwinding the stack
#: before it re-raises.  Anything else means the block holds real source.
_HANDLER_NOISE = frozenset((
    'COPY', 'SWAP', 'POP_TOP', 'POP_EXCEPT', 'PUSH_EXC_INFO',
    'CLEANUP_THROW', 'CALL_INTRINSIC_1', 'DUP_TOP', 'END_SEND',
    'STORE_FAST', 'STORE_NAME', 'STORE_GLOBAL', 'STORE_DEREF',
))

#: Opcodes a ``with`` handler walks through on its way out, before it implicitly
#: returns ``None``.
_WITH_TAIL_OPS = _HANDLER_NOISE | frozenset((
    'WITH_EXCEPT_START', 'POP_JUMP_IF_TRUE', 'RERAISE',
))

#: Opcodes that end an expression statement.  Used to bound the run of
#: instructions that make up the ``return`` 3.12 copies behind a ``with``
#: handler, so the copy can be recognised by comparing the two runs.
_STMT_BREAK_OPS = frozenset((
    'POP_TOP', 'STORE_FAST', 'STORE_NAME', 'STORE_GLOBAL', 'STORE_DEREF',
    'STORE_ATTR', 'STORE_SUBSCR', 'POP_BLOCK', 'POP_EXCEPT',
    'JUMP_FORWARD', 'JUMP_BACKWARD', 'JUMP_BACKWARD_NO_INTERRUPT',
    'JUMP_ABSOLUTE', 'RETURN_VALUE', 'RETURN_CONST', 'RERAISE',
))


def _resolve(raw, code):
    """Resolve one argument the way the 3.9 disassembler would.

    ``dis`` already decodes name, local, free, constant and compare arguments
    correctly for the running interpreter -- including the 3.11+ packing of
    ``LOAD_GLOBAL``/``LOAD_ATTR`` into a single ``arg`` -- so those are taken
    verbatim.  Only jumps need converting, because 3.11's forward/backward
    families report their target in ``argval`` as an offset either way.
    """
    opname = raw.opname
    arg = raw.arg
    if arg is None:
        return None
    if opname in _JUMP_OPS or opname.startswith('POP_JUMP'):
        if raw.argval is not None:
            return int(raw.argval)
        return arg
    if opname in ('LOAD_CONST', 'RETURN_CONST'):
        return code.co_consts[arg]
    return raw.argval


def _exception_entries(code):
    """Decode ``co_exceptiontable`` into ``(start, end, target, depth, lasti)``.

    3.11's ``dis`` exposes a private parser for the table; fall back to the
    documented varint encoding so the rewriter keeps working if that helper
    ever moves.
    """
    parser = getattr(dis, '_parse_exception_table', None)
    if parser is not None:
        return list(parser(code))

    class _Entry(tuple):
        __slots__ = ()

        def __new__(cls, start, end, target, depth, lasti):
            return tuple.__new__(cls, (start, end, target, depth, lasti))

        start = property(lambda self: self[0])
        end = property(lambda self: self[1])
        target = property(lambda self: self[2])
        depth = property(lambda self: self[3])
        lasti = property(lambda self: self[4])

    data = getattr(code, 'co_exceptiontable', b'')
    entries = []
    index = 0
    start = 0

    def read_varint():
        nonlocal index
        value = 0
        shift = 0
        while True:
            byte = data[index]
            index += 1
            value |= (byte & 0x3F) << shift
            if not byte & 0x40:
                return value
            shift += 6

    while index < len(data):
        start = read_varint() * 2
        length = read_varint() * 2
        target = read_varint() * 2
        depth_lasti = read_varint()
        entries.append(_Entry(start, start + length, target,
                              depth_lasti >> 1, bool(depth_lasti & 1)))
    return entries


def _stack_effect(raw):
    """Net stack growth of one instruction, or 0 when it cannot be computed."""
    try:
        return dis.stack_effect(raw.opcode, raw.arg)
    except (ValueError, IndexError, KeyError, TypeError):
        return 0


def _repr_of(opname, arg, argval):
    if arg is None:
        return ''
    if opname == 'LOAD_CONST':
        if isinstance(argval, str):
            return repr(argval)
        if hasattr(argval, 'co_code'):
            return '<code object %s>' % getattr(argval, 'co_name', '?')
        return repr(argval)
    if opname in _JUMP_OPS or opname.startswith('POP_JUMP'):
        return 'to %s' % argval
    if opname == 'COMPARE_OP':
        return str(argval)
    return str(argval)


class _Shape(object):
    """What the single analysis pass decided about each instruction."""

    def __init__(self):
        self.methods = set()      # offsets of LOAD_ATTR that mean LOAD_METHOD
        self.calls = {}           # offset of CALL -> 3.9 call opcode
        self.kw_names = {}        # offset of CALL -> keyword name tuple
        self.decorators = set()   # offsets of CALL that apply a decorator


def _fold_guards(instructions, loop_offsets):
    """Rebuild an ``if`` guard inside an inlined comprehension body.

    3.12 skips to the next clause when the guard holds and jumps back to the
    loop head when it does not::

        POP_JUMP_IF_TRUE  <next clause>
        JUMP_BACKWARD     <loop head>

    3.9 guarded the element with a single ``POP_JUMP_IF_FALSE`` aimed straight
    at the loop head, which is the shape the stock comprehension reader
    recognises.  Folding the pair also moves the guard onto the loop head's own
    offset, so its target still resolves inside the synthetic code object.

    Every clause of a multi-clause comprehension has its own head, and each
    guard folds onto the head of the clause it belongs to, so all of them have
    to be accepted rather than just the outermost one.
    """
    out = []
    index = 0
    total = len(instructions)
    while index < total:
        cur = instructions[index]
        following = instructions[index + 1] if index + 1 < total else None
        if cur.opname in ('POP_JUMP_IF_FALSE', 'POP_JUMP_IF_TRUE') \
                and following is not None \
                and following.opname in ('JUMP_ABSOLUTE', 'JUMP_FORWARD') \
                and following.argval in loop_offsets:
            out.append(Instruction(
                offset=following.argval,
                opcode=cur.opcode,
                opname='POP_JUMP_IF_FALSE',
                arg=None,
                argval=following.argval,
                argrepr='to %s' % following.argval,
                line_no=cur.line_no,
                is_jump_target=True,
            ))
            index += 2
            continue
        out.append(cur)
        index += 1
    return out


class Rewriter(object):
    """Rewrite one 3.11 code object into the 3.9 instruction stream."""

    #: The ``BUILD_*`` that opens each kind of inlined comprehension, and the
    #: name of the nested code object 3.9 would have called.
    _COMP_BUILD = {
        'BUILD_LIST': '<listcomp>',
        'BUILD_SET': '<setcomp>',
        'BUILD_MAP': '<dictcomp>',
    }

    #: The same mapping the other way round, for re-emitting the container.
    _COMP_OPEN = {
        '<listcomp>': 'BUILD_LIST',
        '<setcomp>': 'BUILD_SET',
        '<dictcomp>': 'BUILD_MAP',
    }

    def __init__(self, code):
        self.code = code
        self.version = sys.version_info[:2]
        self.raw = self._normalise_raw(
            list(dis.get_instructions(code)))
        # 3.11 kept a dedicated ``LOAD_METHOD``; 3.12 dropped it and shifted the
        # ``LOAD_ATTR`` name index left by one, leaving bit 0 as the method flag.
        self.attr_method_bit = None if self.version == (3, 11) else 0
        self.jump_targets = set()
        for raw in self.raw:
            if raw.opcode in dis.hasjabs or raw.opcode in dis.hasjrel:
                if raw.argval is not None:
                    self.jump_targets.add(int(raw.argval))
        self._drops = set()
        self._retarget = {}
        self._loop_breaks = {}
        self._handler_heads = set()
        #: 3.14 opens a ``with`` block with ``COPY``/``LOAD_SPECIAL`` instead of
        #: ``BEFORE_WITH``; the anchor offset maps to the instructions that make
        #: up the prefix (the ``SETUP_WITH`` replaces all of them).
        self.with_anchors = {}
        #: A ``CONVERT_VALUE`` waiting for the ``FORMAT_*`` that consumes it.
        #: 3.13 split 3.9's ``FORMAT_VALUE`` (conversion + spec in one opcode)
        #: into ``CONVERT_VALUE`` followed by ``FORMAT_SIMPLE`` /
        #: ``FORMAT_WITH_SPEC``; the conversion applies to the outer value
        #: even when the spec expression is formatted in between.
        self._pending_conversion = None
        self.with_setups, self.with_closes, self.with_swaps, \
            self.with_exits = self._analyse_with()
        self.try_setups, self.try_closes = self._analyse_try()
        self.supers = self._analyse_super()
        self.comprehensions = self._analyse_comprehensions()
        self._mark_dead_handlers()
        self._redirect_handler_exits()
        self._analyse_exception_loop_exits()

    def _normalise_raw(self, raw_list):
        """Fold 3.13/3.14-only encodings onto the 3.9 vocabulary.

        The rest of the rewriter keys every decision off ``opname`` and
        ``argval``, so the quirks are removed once, up front:

        * ``TO_BOOL`` and ``NOT_TAKEN`` are stack-neutral bookkeeping;
        * 3.13's paired fast opcodes are expanded into the two plain opcodes;
        * 3.14's borrowed loads are just loads of the same local;
        * ``SET_FUNCTION_ATTRIBUTE`` is folded into the ``MAKE_FUNCTION`` flags
          it belongs to (3.9 spells the same information as an oparg).
        """
        expanded = []
        for raw in raw_list:
            opname = raw.opname
            if opname in ('TO_BOOL', 'NOT_TAKEN', 'CACHE'):
                continue
            if opname in ('LOAD_FAST_BORROW', 'LOAD_FAST_MAYBE_NULL'):
                raw = raw._replace(opname='LOAD_FAST')
                opname = 'LOAD_FAST'
            elif opname in _FAST_PAIR_OPS:
                expanded.extend(self._expand_pair(raw))
                continue
            expanded.append(raw)
        if self.version >= (3, 13):
            expanded = self._fold_function_attributes(expanded)
        return expanded

    @staticmethod
    def _expand_pair(raw):
        """Split one paired fast opcode into its two plain halves."""
        high = (raw.arg or 0) >> 4
        low = (raw.arg or 0) & 0xF
        names = raw.argval if isinstance(raw.argval, tuple) else (None, None)
        if raw.opname in ('LOAD_FAST_LOAD_FAST',
                          'LOAD_FAST_BORROW_LOAD_FAST_BORROW'):
            first, second = 'LOAD_FAST', 'LOAD_FAST'
        elif raw.opname == 'STORE_FAST_STORE_FAST':
            first, second = 'STORE_FAST', 'STORE_FAST'
        else:
            first, second = 'STORE_FAST', 'LOAD_FAST'
        return [
            raw._replace(opname=first, arg=high, argval=names[0]),
            raw._replace(opname=second, arg=low, argval=names[1]),
        ]

    @staticmethod
    def _fold_function_attributes(raw_list):
        """Turn 3.13's ``MAKE_FUNCTION`` + ``SET_FUNCTION_ATTRIBUTE`` into 3.9.

        3.9 pushes every attribute before the code object and passes a bitmask
        to ``MAKE_FUNCTION``; 3.13 pushes the code object once and applies each
        attribute afterwards.  The bit values (and the stack order) match, so
        the flags are OR-ed into the ``MAKE_FUNCTION`` and the ``SET`` dropped.

        A 3.14 function with annotations is preceded by a generated
        ``__annotate__`` function that the flag does not describe.  It is
        compiler machinery -- the 3.9 reader has no equivalent -- so the pair
        that builds it is dropped along with the attribute.
        """
        result = list(raw_list)
        drop = set()
        for index, raw in enumerate(raw_list):
            if raw.opname != 'SET_FUNCTION_ATTRIBUTE':
                continue
            drop.add(index)
            make = index - 1
            while make >= 0 and raw_list[make].opname != 'MAKE_FUNCTION':
                make -= 1
            if make < 0:
                continue
            if raw.arg == 16:
                if make >= 3 \
                        and raw_list[make - 2].opname == 'MAKE_FUNCTION' \
                        and raw_list[make - 3].opname == 'LOAD_CONST' \
                        and getattr(raw_list[make - 3].argval, 'co_name',
                                    None) == '__annotate__':
                    drop.add(make - 2)
                    drop.add(make - 3)
                continue
            target = result[make]
            result[make] = target._replace(
                arg=(target.arg or 0) | (raw.arg or 0))
        return [raw for index, raw in enumerate(result) if index not in drop]


    def _analyse_super(self):
        """Locate 3.12's ``LOAD_SUPER_ATTR`` and undo the ``super()`` shortcut.

        3.12 gave ``super()`` its own opcode, so a bare ``super().m`` became::

            LOAD_GLOBAL super
            LOAD_DEREF __class__       # the two operands, implicit
            LOAD_FAST self
            LOAD_SUPER_ATTR m

        where 3.9 built the attribute on a real ``super`` object::

            LOAD_GLOBAL super
            CALL_FUNCTION 0
            LOAD_ATTR m

        The instruction therefore has to grow a call in front of it, and the
        operands 3.12 pushes implicitly have to go -- unless the source spelled
        them out, in which case they are the call's arguments and stay.
        """
        raw_list = self.raw
        found = {}
        for index, raw in enumerate(raw_list):
            if raw.opname != 'LOAD_SUPER_ATTR':
                continue
            start = index - 1
            while start >= 0 and raw_list[start].opname in _SUPER_OPERANDS:
                start -= 1
            operands = raw_list[start + 1:index]
            # The ``super`` lookup itself heads the run; everything after it is
            # the call's argument list.
            argc = len(operands) - 1 if operands else 0
            implicit = len(operands) == 3 \
                and operands[1].opname == 'LOAD_DEREF' \
                and operands[1].argval == '__class__'
            if implicit:
                for raw_operand in operands[1:]:
                    self._drops.add(raw_operand.offset)
                argc = 0
            found[raw.offset] = (argc, bool(raw.arg & 1))
        return found

    def _analyse_comprehensions(self, raw_list=None):
        """Locate 3.12's inlined comprehensions and describe their loops.

        3.12 stopped building a nested code object for a list/set/dict
        comprehension and instead laid the loop out inline::

            LOAD_FAST_AND_CLEAR x        # bind the target, drop the outer slot
            SWAP 2
            BUILD_LIST 0
            SWAP 2
            FOR_ITER ...
            END_FOR
            SWAP 2
            STORE_FAST x                 # restore the outer slot

        The ``BUILD_*`` between the two ``SWAP 2``s opens the comprehension and
        the matching ``END_FOR`` closes it; every ``FOR_ITER`` in between is one
        ``for`` clause of a multi-clause comprehension.
        """
        raw_list = self.raw if raw_list is None else raw_list
        found = {}
        for n, raw in enumerate(raw_list):
            name = self._COMP_BUILD.get(raw.opname)
            if name is None or raw.arg:
                continue
            before = raw_list[n - 1] if n else None
            after = raw_list[n + 1] if n + 1 < len(raw_list) else None
            if before is None or before.opname != 'SWAP' \
                    or after is None or after.opname != 'SWAP':
                continue
            depth = 0
            end = None
            for k in range(n + 1, len(raw_list)):
                opname = raw_list[k].opname
                if opname == 'FOR_ITER':
                    depth += 1
                elif opname == 'END_FOR':
                    depth -= 1
                    if depth == 0:
                        end = k
                        break
            if end is None:
                continue
            loops = [k for k in range(n + 1, end)
                     if raw_list[k].opname == 'FOR_ITER']
            # Key the entry on the first instruction 3.12 emits for the
            # comprehension, so the whole run -- including the locals it
            # borrows and the container it opens -- is replaced in one go.
            head = n
            while head > 0 and raw_list[head - 1].opname in (
                    'SWAP', 'LOAD_FAST_AND_CLEAR'):
                head -= 1
            borrowed = [raw_list[k].argval for k in range(head, n)
                       if raw_list[k].opname == 'LOAD_FAST_AND_CLEAR']
            # 3.13 pops the exhausted iterator's value and 3.14 pops the
            # iterator itself; 3.12 leaves both to ``END_FOR``.  Neither has a
            # 3.9 counterpart, and the result must stay on the stack for the
            # store that follows, so the pops are dropped with the loop.
            resume = end + 1
            while resume < len(raw_list) \
                    and raw_list[resume].opname in ('POP_TOP', 'POP_ITER'):
                self._drops.add(raw_list[resume].offset)
                resume += 1
            self._mark_restores(raw_list, resume, borrowed)
            found[raw_list[head].offset] = (name, n, end, loops, resume)
        return found

    def _mark_restores(self, raw_list, index, borrowed):
        """Flag the bookkeeping that puts the borrowed locals back.

        3.12 borrows each name the comprehension binds with
        ``LOAD_FAST_AND_CLEAR`` and restores every one of them with a
        ``SWAP``/``STORE_FAST`` pair once the loop is done.  Where the
        comprehension's own assignment lands in that run depends on whether the
        result is stored in a local or a class-level name::

            STORE_FAST a     # a = [x for x in ...]
            STORE_FAST x     # the slot the comprehension borrowed

            SWAP 3
            STORE_FAST i     # the slots the comprehension borrowed
            STORE_NAME vals  # vals = [i for i in ...]

        so the restores are recognised by the names they write rather than by
        their position.  None of it exists in 3.9, where the comprehension ran
        in a frame of its own.
        """
        total = len(raw_list)
        while index < total and raw_list[index].opname in ('POP_TOP',
                                                           'POP_ITER'):
            index += 1
        run = []
        while index < total:
            opname = raw_list[index].opname
            if opname == 'SWAP' or opname in _STORE_OPS:
                run.append(index)
                index += 1
                continue
            break
        if not borrowed:
            return
        restorers = [k for k in run
                     if raw_list[k].opname in _STORE_OPS
                     and raw_list[k].argval in borrowed]
        if len(restorers) < len(borrowed):
            return
        drops = set(restorers)
        first = run.index(restorers[0])
        # The ``SWAP`` in front of the first restore lifts the saved values
        # back above the result, so it belongs to the restores too.
        if first and raw_list[run[first - 1]].opname == 'SWAP':
            drops.add(run[first - 1])
        for k in drops:
            self._drops.add(raw_list[k].offset)

    def _mark_dead_handlers(self):
        """Flag the exception-table handler blocks 3.9 never had.

        3.11+ protects a region with a ``co_exceptiontable`` entry and parks
        the unwinding code wherever the optimizer likes -- usually past the
        final ``RETURN_VALUE``.  Nothing branches there, so the stock
        decompiler walks it as if it were straight-line source and appends the
        ``raise``/``while True: pass`` noise it finds.

        Such a block is recognisable because the table is its only way in, it
        does nothing but unwind the stack, and it ends by leaving the function
        -- re-raising, returning ``None`` for a handler that swallowed the
        exception, or jumping back into the machinery it interrupted.  Any
        other opcode means the block holds real source and must be kept.

        A handler that handles an exception leaves through a *backward* jump to
        the tail it duplicated, which the decompiler would otherwise read as a
        loop back to the statement before the protected region.  3.9 reached
        the same tail by jumping *forward* over its own cleanup, so the jump is
        re-aimed at the merge point instead.
        """
        raw_list = self.raw
        by_offset = {raw.offset: n for n, raw in enumerate(raw_list)}
        for entry in _exception_entries(self.code):
            start = by_offset.get(entry.target)
            if start is None or entry.target in self._handler_heads:
                continue
            index = start
            while index < len(raw_list):
                opname = raw_list[index].opname
                if opname in ('RERAISE', 'RETURN_CONST') or opname in _JUMP_OPS:
                    for k in range(start, index + 1):
                        self._drops.add(raw_list[k].offset)
                    break
                if opname not in _HANDLER_NOISE:
                    break
                index += 1

    def _redirect_handler_exits(self):
        """Re-aim a handler's backward exit jump at the code after the block.

        3.11 duplicated the tail that follows a protected region and let the
        handler jump *back* into it, while 3.9 jumped forward over the block's
        own cleanup to a single copy of that tail::

            STORE_NAME docx_support
            POP_EXCEPT
            JUMP_BACKWARD  -> the class body above   # 3.11/3.12
            RERAISE

        The backward jump reads to the stock decompiler as the back edge of a
        ``while`` loop, so the whole module turns into one enormous loop and
        the function is decompiled over and over.  The duplicated tail is
        emitted separately, so the jump only has to skip the handler: aiming
        it past the end of the block restores the 3.9 shape.

        In 3.12 module-level code, the compiler places the tail *before* the
        handler (at entry.end) rather than after.  The handler then jumps
        backward to entry.end.  We retarget the jump to the merge point (past
        all handlers) and save the tail instructions to be emitted at the
        merge point.

        The same shape shows up inside a function: there the tail is the code
        that follows the whole ``try`` statement, and the handler jumps back
        to it.  It is moved past the handler as well, otherwise the reader
        takes everything between the body and the handler for the ``else``
        clause and swallows the tail.
        """
        raw_list = self.raw
        by_offset = {raw.offset: n for n, raw in enumerate(raw_list)}
        for entry in _exception_entries(self.code):
            start = by_offset.get(entry.target)
            if start is None:
                continue
            for index in range(start, len(raw_list)):
                raw = raw_list[index]
                if raw.opname == 'RERAISE':
                    break
                if raw.opname not in _JUMP_OPS:
                    continue
                target = int(raw.argval or 0)
                if target >= entry.target:
                    # Already leaves the handler; nothing to re-aim.
                    break
                if target < entry.end:
                    # This is a real loop continue, not a duplicated tail.
                    break
                # The code the handler jumps back to is the code that follows
                # the whole ``try`` statement.  3.11/3.12 place it before the
                # handler, where the reader would take it for the ``else``
                # clause, so it is moved past the handler and the jump is
                # re-aimed at its new home.
                merge = self._merge_offset(entry)
                self._retarget[raw.offset] = merge
                self._save_tail_for_merge(target, merge)
                break

    def _analyse_exception_loop_exits(self):
        """Retarget handler back-edges past dropped loop-head NOPs."""
        raw_list = self.raw
        by_offset = {raw.offset: index for index, raw in enumerate(raw_list)}
        jump_ops = set(dis.hasjabs) | set(dis.hasjrel)
        for entry in _exception_entries(self.code):
            if entry.start not in by_offset or entry.target not in by_offset:
                continue
            loop_heads = set()
            for raw in raw_list:
                if raw.offset < entry.target or raw.opcode not in jump_ops \
                        or not isinstance(raw.argval, int) \
                        or raw.argval >= entry.start:
                    continue
                target = by_offset.get(raw.argval)
                if target is not None and raw_list[target].opname == 'NOP':
                    loop_heads.add(raw.argval)
            if not loop_heads:
                continue
            for loop_head in loop_heads:
                target_index = by_offset[loop_head]
                while target_index < len(raw_list) and raw_list[target_index].opname in (
                    'NOP', 'RESUME', 'CACHE'
                ):
                    target_index += 1
                if target_index >= len(raw_list):
                    continue
                target_offset = raw_list[target_index].offset
                self.jump_targets.add(target_offset)
                for raw in raw_list:
                    if raw.opcode in jump_ops and raw.argval == loop_head:
                        self._retarget[raw.offset] = target_offset
            end = by_offset.get(entry.end)
            if end is None or raw_list[end].opname != 'NOP':
                continue
            exit_index = end + 1
            while exit_index < len(raw_list) and raw_list[exit_index].opname in (
                'NOP', 'RESUME', 'CACHE'
            ):
                exit_index += 1
            if exit_index < len(raw_list):
                self._loop_breaks[raw_list[end].offset] = raw_list[exit_index].offset

    def _save_tail_for_merge(self, tail_start, merge_offset):
        """Save tail instructions to be emitted at the merge point.

        3.11/3.12 place the code that follows a ``try`` statement *before* the
        handler, and the handler jumps back to it.  We save these instructions
        to emit them at the merge point (after all handlers).
        """
        raw_list = self.raw
        # Find the handler start (first PUSH_EXC_INFO after tail_start)
        handler_start = None
        for raw in raw_list:
            if raw.offset >= tail_start and raw.opname == 'PUSH_EXC_INFO':
                handler_start = raw.offset
                break
        if handler_start is None:
            return
        # Collect tail instructions (from tail_start to handler_start)
        tail_instructions = []
        for raw in raw_list:
            if tail_start <= raw.offset < handler_start:
                tail_instructions.append(raw)
        if not tail_instructions:
            return
        # Store for emission at merge point
        if not hasattr(self, '_tails_at_merge'):
            self._tails_at_merge = {}
        self._tails_at_merge[merge_offset] = tail_instructions
        # Drop the original tail instructions in place, but remember which
        # offsets were dropped for this reason: ``run`` has to translate them
        # when it re-emits them at the merge point, so it must not skip them
        # there.  Any *other* drop inside the tail range stays in force.
        if not hasattr(self, '_tail_offsets'):
            self._tail_offsets = set()
        for raw in tail_instructions:
            self._drops.add(raw.offset)
            self._tail_offsets.add(raw.offset)

    def _merge_offset(self, entry):
        """Offset just past every handler block belonging to *entry*.

        The handler for one protected region is spread over several table
        entries -- the body, the re-raise path and the final stack cleanup --
        so the merge point is past the last of them, not past the first.
        """
        raw_list = self.raw
        entries = _exception_entries(self.code)
        end = max(other.end for other in entries
                  if other.target >= entry.target)
        index = 0
        while index < len(raw_list) and raw_list[index].offset < end:
            index += 1
        # Skip past all handler noise (POP_EXCEPT, COPY etc.) AND the final
        # RERAISE that terminates the cleanup handler chain, until we reach
        # real code.  Stopping at the first non-noise insn would land inside
        # the cleanup handler (e.g. at RERAISE 1) for 3.12 module-level code.
        while index < len(raw_list) and (
                raw_list[index].opname in _HANDLER_NOISE
                or raw_list[index].opname == 'RERAISE'):
            index += 1
        if index >= len(raw_list):
            return raw_list[-1].offset
        return raw_list[index].offset

    def _lift_comprehension(self, index, spec, out):
        """Emit the 3.9 call shape for one inlined comprehension.

        3.12 leaves the result of a comprehension on the stack by itself;
        3.9 built a function, called it with the iterator and popped the
        result.  Re-emitting the call lets the stock decompiler run its
        existing ``_build_comprehension`` over the loop body unchanged.

        The trailing ``SWAP``/``STORE_FAST`` pair only restores the outer
        local the comprehension borrowed, and the ``END_FOR`` only closes the
        loop; neither has a 3.9 counterpart inside a comprehension body.
        """
        name, start, end, loops, resume = spec
        raw_list = self.raw
        # 3.9 opened a comprehension with ``BUILD_*`` then loaded the incoming
        # iterator as ``.0``; 3.12 clears the borrowed local instead.  Swap that
        # for the load so the body reads the same.
        head = loops[0]
        while head > start + 1 and raw_list[head - 1].opname \
                != 'LOAD_FAST_AND_CLEAR':
            head -= 1
        prologue = [self._make(raw_list[head], 'LOAD_FAST', 0, '.0')]
        body = _fold_guards(
            self._translate_range(loops[0], end),
            frozenset(raw_list[k].offset for k in loops),
        )
        body = [ins for ins in body if ins.opname != 'END_FOR']
        body.append(self._make(raw_list[end], 'RETURN_VALUE', None, None,
                               line_no=None))
        container = self._make(raw_list[start], self._COMP_OPEN[name], 0, 0)
        synthetic = _SyntheticComprehension(name,
                                           [container] + prologue + body)
        for opname, arg, argval in (('LOAD_CONST', None, synthetic),
                                    ('LOAD_CONST', None, name),
                                    ('MAKE_FUNCTION', 0, 0)):
            out.append(self._make(raw_list[start], opname, arg, argval,
                                  line_no=None))
        out.append(self._make(raw_list[end], 'CALL_FUNCTION', 1, 1))
        # A ``POP_BLOCK`` the table anchored on the run this call replaces, or on
        # the bookkeeping right after it that restores the locals it borrowed,
        # has no instruction left to follow -- so the close moves onto the call,
        # which is where 3.9 put it too.
        inside = []
        for k in range(index, resume):
            inside.append(k)
        probe = resume
        while probe < len(raw_list) \
                and raw_list[probe].offset in self._drops:
            inside.append(probe)
            probe += 1
        inside = [k for k in inside if raw_list[k].offset in self.try_closes]
        for k in inside:
            del self.try_closes[raw_list[k].offset]
        if inside:
            out.append(self._make(raw_list[end], 'POP_BLOCK', None, None,
                                  line_no=None))
        return resume

    def _translate_range(self, start, end):
        """Translate ``self.raw[start:end]`` with the same rules as ``run``.

        The slice is handed to a throwaway rewriter so that the nested
        comprehensions of a multi-clause expression are lifted independently
        without the outer scan losing its place.
        """
        inner = Rewriter.__new__(Rewriter)
        inner.code = self.code
        inner.version = self.version
        inner.raw = self.raw[start:end]
        inner.attr_method_bit = self.attr_method_bit
        inner.jump_targets = self.jump_targets
        inner.with_setups = {}
        inner.with_anchors = {}
        inner._pending_conversion = None
        inner.async_with_setups = {}
        inner.with_targets = set()
        inner.with_closes = {}
        inner.with_swaps = set()
        inner.with_exits = set()
        inner.try_setups = {}
        inner.try_closes = {}
        inner.try_before = {}
        inner.try_replace = {}
        inner.name_closes = {}
        inner._drops = set()
        inner._retarget = {}
        inner._loop_breaks = {}
        inner._handler_heads = set()
        inner.supers = inner._analyse_super()
        inner.comprehensions = inner._analyse_comprehensions()
        inner._mark_dead_handlers()
        inner._redirect_handler_exits()
        return inner.run()

    def _reachable_offsets(self):
        """Offsets reachable from the entry along ordinary control flow.

        Exception handlers are entered by the interpreter rather than by a
        jump, so the walk never steps into one.  An exception-table entry that
        covers an unwind path therefore ends at an offset that is unreachable,
        which is what tells it apart from the body's own close.
        """
        cached = getattr(self, "_reachable_cache", None)
        if cached is not None:
            return cached
        raw_list = self.raw
        by_offset = {r.offset: n for n, r in enumerate(raw_list)}
        n = len(raw_list)
        conditional = {
            "POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE",
            "POP_JUMP_FORWARD_IF_FALSE", "POP_JUMP_FORWARD_IF_TRUE",
            "POP_JUMP_BACKWARD_IF_FALSE", "POP_JUMP_BACKWARD_IF_TRUE",
            "JUMP_IF_FALSE_OR_POP", "JUMP_IF_TRUE_OR_POP", "FOR_ITER",
            "SEND", "JUMP_IF_NOT_EXC_MATCH", "CHECK_EXC_MATCH",
        }
        unconditional = {"JUMP_ABSOLUTE", "JUMP_FORWARD", "JUMP_BACKWARD",
                         "JUMP", "JUMP_BACKWARD_NO_INTERRUPT"}
        terminal = {"RETURN_VALUE", "RETURN_CONST", "RAISE_VARARGS",
                    "RERAISE"}
        seen = set()
        work = [0]
        while work:
            i = work.pop()
            while 0 <= i < n and i not in seen:
                seen.add(i)
                ins = raw_list[i]
                op = ins.opname
                if op in terminal:
                    break
                if op in unconditional:
                    target = by_offset.get(ins.argval)
                    if target is not None:
                        work.append(target)
                    break
                if op in conditional:
                    target = by_offset.get(ins.argval)
                    if target is not None:
                        work.append(target)
                    i += 1
                    continue
                i += 1
        result = {raw_list[i].offset for i in seen}
        self._reachable_cache = result
        return result

    def _analyse_with(self):
        """Map each ``BEFORE_WITH`` to the 3.9 ``SETUP_WITH`` it stands for.

        3.11 replaced the block stack with ``co_exceptiontable``.  A ``with``
        body is covered by an entry that begins right *after* the
        ``BEFORE_WITH`` and ends where the implicit ``__exit__`` call starts,
        and whose handler begins with ``PUSH_EXC_INFO`` / ``WITH_EXCEPT_START``
        -- the pair the 3.9 ``SETUP_WITH`` branched to.  Both ends of the body
        are needed, because the ``POP_BLOCK`` that closed the 3.9 block has no
        counterpart in 3.11 and has to be synthesised.

        The closing offset is not always a fresh instruction: when the body
        ends in ``return`` or an assignment that leaves exactly one extra value
        behind, 3.12 folds the block pop into the ``SWAP`` that rotates the
        pending return value out of the way.  Such an offset is recorded in
        *swaps* so ``run`` can emit ``POP_BLOCK`` before the rotation.

        A body containing a comprehension is covered by several entries rather
        than one, all aiming at the same handler, so once the handler is known
        every entry aiming at it is merged and the block is closed where the
        last of them ends.  Entries that end at or after the handler itself
        cover the re-raise tail rather than the body and are left out.
        """
        by_offset = {raw.offset: n for n, raw in enumerate(self.raw)}
        setups = {}
        closes = {}
        targets = set()
        ends = {}
        swaps = set()
        exits = set()
        self.async_with_setups = {}
        self.with_anchors = {}
        for entry in _exception_entries(self.code):
            start = by_offset.get(entry.start)
            if start is None or start == 0:
                continue
            setup = self._with_setup_index(start - 1)
            if setup is None:
                continue
            handler = by_offset.get(entry.target)
            if handler is None:
                continue
            ops = [self.raw[handler + k].opname
                   for k in range(2) if handler + k < len(self.raw)]
            if ops[:2] != ['PUSH_EXC_INFO', 'WITH_EXCEPT_START']:
                continue
            anchor = self.raw[setup]
            setups[anchor.offset] = self.raw[handler + 1].offset
            if anchor.opname == 'COPY':
                # 3.14 spells the prefix out instead of a single
                # ``BEFORE_WITH``: ``COPY``, the two special lookups, two
                # rotations and the ``__enter__`` call all become the 3.9
                # ``SETUP_WITH`` that the compiler's block stack implied.
                self.with_anchors[anchor.offset] = self._with_prefix_length(setup)
            targets.add(entry.target)
            if self.raw[setup].opname == 'BEFORE_ASYNC_WITH':
                # 3.9 opened the block *after* awaiting ``__aenter__()``.
                self.async_with_setups[self.raw[start].offset] = \
                    self.raw[handler + 1].offset
            self._drop_with_handler_tail(handler)
        self.with_targets = targets
        # An entry whose range covers another handler's target is the unwind
        # tail of a nested block, not body source: the nested handler runs
        # while the outer block is being torn down, and the table records that
        # region against the outer handler as well.  Anchoring the close there
        # parks the ``POP_BLOCK`` inside the exception path instead of in front
        # of the ``__exit__`` call it closes, which is what breaks
        # ``with a as x, b as y:`` -- the outer block then reads as ending
        # inside the handler tail and the 3.9 walk runs off the stream.
        handler_targets = {e.target for e in _exception_entries(self.code)}
        for entry in _exception_entries(self.code):
            if entry.target not in targets or entry.end >= entry.target:
                continue
            if any(entry.start <= t < entry.end
                   for t in handler_targets if t != entry.target):
                continue
            position = by_offset.get(entry.end)
            if position is None:
                continue
            # The range must stop where the body's own ``__exit__`` call starts.
            # 3.11 records the handler's unwinding call the same way, so there
            # only the three ``None`` operands tell the two apart.  3.12 reuses
            # one operand slot for the outermost block of an empty body, so the
            # looser "a call follows" test is needed there as well.
            if not self._close_starts_exit(position) \
                    and (self.attr_method_bit is None
                         or self._find_exit_call(position) is None):
                continue
            ends.setdefault(entry.target, set()).add(entry.end)
        # A handler that unwinds an enclosing block runs its ``__exit__`` too,
        # so the table records a second range against the outer handler.  That
        # range starts inside the nested handler and is therefore unreachable
        # along ordinary control flow; the body's own close is the last
        # reachable one.  Comprehension bodies, which are covered by several
        # consecutive reachable ranges, still close at the last of them.
        reachable = self._reachable_offsets()
        resolved = []
        for target, candidates in ends.items():
            on_path = [e for e in candidates if e in reachable]
            end = max(on_path) if on_path else max(candidates)
            position = by_offset.get(end)
            if position is None:
                continue
            resolved.append((end, position))
        for end, position in sorted(resolved):
            closes[end] = end
            if self.raw[position].opname == 'SWAP':
                swaps.add(end)
            exit_call = self._find_exit_call(position)
            if exit_call is not None:
                exits.add(exit_call.offset)
        return setups, closes, swaps, exits

    def _with_setup_index(self, index):
        """Index of the instruction that opens the block *index* belongs to.

        An ``async with`` puts an ``await __aenter__()`` between the
        ``BEFORE_ASYNC_WITH`` and the body the table protects, so the protected
        range does not begin right after the setup.  Walk back over that await
        to the setup it belongs to.

        3.14 has no ``BEFORE_WITH`` at all: the block opens with the
        ``COPY``/``LOAD_SPECIAL`` sequence that binds ``__enter__`` and
        ``__exit__`` before calling ``__enter__``.
        """
        if index >= 0 and self.raw[index].opname == 'CALL':
            anchor = self._with_anchor_314(index)
            if anchor is not None:
                return anchor
        while index >= 0:
            opname = self.raw[index].opname
            if opname in ('BEFORE_WITH', 'BEFORE_ASYNC_WITH'):
                return index
            if opname not in ('SEND', 'YIELD_VALUE', 'RESUME',
                              'JUMP_BACKWARD_NO_INTERRUPT', 'END_SEND',
                              'CLEANUP_THROW', 'LOAD_CONST', 'GET_AWAITABLE'):
                return None
            index -= 1
        return None

    def _with_anchor_314(self, call_index):
        """Index of the ``COPY`` that opens a 3.14 ``with`` block, if any.

        The compiler lays the block out as::

            <manager>
            COPY 1
            LOAD_SPECIAL __exit__
            SWAP 2
            SWAP 3
            LOAD_SPECIAL __enter__
            CALL 0

        and protects the code that follows ``CALL 0``.  All six instructions
        stand for the single 3.9 ``SETUP_WITH``.
        """
        raw_list = self.raw
        if call_index < 5:
            return None
        expected = ('COPY', 'LOAD_SPECIAL', 'SWAP', 'SWAP', 'LOAD_SPECIAL',
                    'CALL')
        run = raw_list[call_index - 5:call_index + 1]
        if tuple(raw.opname for raw in run) != expected:
            return None
        if run[0].arg != 1:
            return None
        if _special_method(run[1].arg) != '__exit__' \
                or _special_method(run[4].arg) != '__enter__':
            return None
        return call_index - 5

    @staticmethod
    def _with_prefix_length(setup_index):
        """How many instructions a 3.14 ``with`` prefix occupies."""
        return 6


    def _find_exit_call(self, position):
        """Locate the ``__exit__`` call that closes a ``with`` body.

        It is the first call after the protected range, and only the three
        ``None`` operands 3.12 pushes for it may sit in between.  3.12 counts
        the already-bound ``__exit__`` itself in the ``CALL`` argument, so the
        call carries one fewer argument than the 3.9 ``CALL_FUNCTION`` that
        pops the method together with its three ``None`` operands.
        """
        raw_list = self.raw
        for index in range(position, len(raw_list)):
            opname = raw_list[index].opname
            if opname in ('CALL', 'CALL_KW'):
                return raw_list[index]
            if opname not in _EXIT_OPERANDS:
                return None
        return None

    def _close_starts_exit(self, position):
        """True when the three ``None`` operands of an ``__exit__`` call begin
        at *position*.

        A handler that unwinds a ``with`` also calls ``__exit__``, so the
        exception table records a range against that handler as well; the call
        the body ends in is the only one spelled ``__exit__(None, None, None)``
        and is therefore the one with exactly three ``None`` operands in front
        of it.  The rotation that lifts a pending value out of the way may
        precede them.
        """
        raw_list = self.raw
        index = position
        while index < len(raw_list) and raw_list[index].opname in (
                'SWAP', 'COPY', 'ROT_TWO', 'ROT_THREE', 'ROT_FOUR'):
            index += 1
        operands = 0
        while index < len(raw_list) \
                and raw_list[index].opname in ('LOAD_CONST', 'LOAD_SMALL_INT') \
                and raw_list[index].argval is None:
            operands += 1
            index += 1
        while index < len(raw_list) and raw_list[index].opname in ('PRECALL',
                                                                   'NOP'):
            index += 1
        return operands >= 3 and index < len(raw_list) \
            and raw_list[index].opname in ('CALL', 'CALL_KW')

    def _drop_with_handler_tail(self, handler: int) -> None:
        """Drop the whole unwind path of a ``with`` handler.

        Once ``__exit__`` has run, the handler only pops what it pushed and then
        leaves the block: 3.12 with ``RETURN_CONST``, 3.11 with an implicit
        ``LOAD_CONST None; RETURN_VALUE``, and with a body that computes its
        return value with a jump back to the code behind the block.  3.9 had no
        such tail, so leaving it in makes the recovered body end in a stray
        ``return`` -- and, in 3.12, parks a backward jump in the middle of the
        enclosing ``try`` body, which the reader reads as a loop.

        3.11 ends the handler with the stack pops and falls through to the
        code behind the block, so there is no jump to recognise.  The shape of
        the handler is fixed, though: it always ends with
        ``POP_TOP; POP_EXCEPT; POP_TOP; POP_TOP``, and that is where it ends.
        """
        raw_list = self.raw
        index = handler
        tail: List[str] = []
        while index < len(raw_list):
            opname = raw_list[index].opname
            if opname == 'RETURN_CONST':
                self._drops.update(
                    raw.offset for raw in raw_list[handler:index + 1]
                )
                return
            if opname == 'LOAD_CONST' and raw_list[index].argval is None \
                    and index + 1 < len(raw_list) \
                    and raw_list[index + 1].opname in ('RETURN_VALUE',
                                                       'RETURN_CONST'):
                self._drops.update(
                    raw.offset for raw in raw_list[handler:index + 2]
                )
                return
            if opname in ('JUMP_BACKWARD', 'JUMP_BACKWARD_NO_INTERRUPT'):
                # The handler resumes the code behind the block, so the jump
                # points back into the enclosing body.
                self._drops.update(
                    raw.offset for raw in raw_list[handler:index + 1]
                )
                return
            # Everything a ``with`` handler legitimately contains on the way out.
            if opname in _WITH_TAIL_OPS:
                tail.append(opname)
                index += 1
                continue
            if tail[-4:] == ['POP_TOP', 'POP_EXCEPT', 'POP_TOP', 'POP_TOP']:
                # The handler ends here: the pops are its last act and the
                # code behind them belongs to the block's surroundings.
                self._drops.update(
                    raw.offset for raw in raw_list[handler:index]
                )
                # 3.12 has no jump from the normal path to the code behind the
                # block -- it *copies* that code after the handler so the
                # handler path can still return the value the body computed.
                # The copy is the same statement as the run that ends right
                # before the handler; leaving it in emits the statement twice.
                copy_end = self._duplicated_exit_run(handler, index)
                if copy_end is not None:
                    self._drops.update(
                        raw.offset for raw in raw_list[index:copy_end]
                    )
            return

    @staticmethod
    def _normalised_opname(instr) -> str:
        """Opcode name with 3.12's checked loads folded onto their plain form.

        The copy 3.12 emits after a handler uses ``LOAD_FAST_CHECK`` where the
        original used ``LOAD_FAST``; the two load the same local.
        """
        if instr.opname == 'LOAD_FAST_CHECK':
            return 'LOAD_FAST'
        return instr.opname

    def _duplicated_exit_run(self, handler: int, after: int):
        """End index of the exit statement 3.12 copies after a ``with`` handler.

        *after* is the first instruction behind the handler.  The block's
        normal path ends right in front of the handler, so the run of
        instructions there is the statement the compiler duplicated; the copy
        behind the handler has to match it instruction for instruction
        (modulo ``LOAD_FAST_CHECK``) before it can be dropped.
        """
        raw_list = self.raw
        index = handler - 1
        if index < 0 or raw_list[index].opname not in (
            'RETURN_VALUE', 'RETURN_CONST'
        ):
            return None
        run = [index]
        index -= 1
        while index >= 0 and len(run) < 8:
            if raw_list[index].opname in _STMT_BREAK_OPS:
                break
            run.append(index)
            index -= 1
        run.reverse()
        before = [(self._normalised_opname(raw_list[i]), raw_list[i].argval)
                  for i in run]

        copy = []
        index = after
        while index < len(raw_list) and len(copy) < len(before):
            opname = self._normalised_opname(raw_list[index])
            if opname in _STMT_BREAK_OPS and opname not in (
                'RETURN_VALUE', 'RETURN_CONST'
            ):
                return None
            copy.append((opname, raw_list[index].argval))
            index += 1
        if copy != before:
            return None
        return index

    def _analyse_try(self):
        """Rebuild the 3.9 ``SETUP_FINALLY``/``POP_BLOCK`` pair from the table.

        3.11 dropped the block stack, so a ``try`` statement survives only as a
        ``co_exceptiontable`` entry covering the region it protects.  3.9 spelled
        the same thing with a ``SETUP_FINALLY`` in front of that region and a
        ``POP_BLOCK`` closing it, both of which have to be synthesised.

        Which 3.9 form is meant is decided by the handler itself:

        * one that only re-raises is a ``finally`` clause, and 3.9 ran the
          clause inline after the body;
        * one that tests the exception type is a real ``except`` clause.

        Entries that cover a handler rather than a body are the block's own
        cleanup and are skipped, as is a region a ``with`` block already owns.
        """
        by_offset = {raw.offset: n for n, raw in enumerate(self.raw)}
        closes = {}
        self.try_before = {}
        self.try_replace = {}
        self.name_closes = {}
        entries = _exception_entries(self.code)
        blocks = []
        claimed = set()
        for entry in entries:
            handler = by_offset.get(entry.target)
            start = by_offset.get(entry.start)
            if handler is None or start is None or start == 0:
                continue
            # The handler must be reachable only from the table, and must not
            # be the one a ``with`` block or a comprehension already claimed.
            if entry.target in self.with_targets \
                    or self.raw[start - 1].offset in self.with_setups:
                continue
            if self.raw[handler].opname != 'PUSH_EXC_INFO':
                continue
            if entry.target in claimed:
                # A region interrupted by a ``with`` comes back as several
                # entries sharing one handler.  3.9 opened and closed the block
                # exactly once, around the whole region, so the later spans
                # must not open a block of their own.
                continue
            claimed.add(entry.target)
            blocks.append((entry.start, entry.target))
        # A nested ``try`` whose protected body is empty -- ``try: return X
        # finally: C`` inside another ``try`` -- leaves no exception-table
        # entry of its own: the clause ``C`` is emitted inline and protected by
        # the *outer* handler, and reappears only as a copy inside its own
        # handler.  Recover the inner block from that copy so the back
        # translation keeps the nesting instead of folding ``C`` into the outer
        # body (which would drop the inner ``try``/``finally`` entirely).
        #
        # Only a single-level nesting (one table block) is recovered here -- the
        # common ``try: return X finally: C`` wrapped in one outer ``try``.  A
        # deeper chain leaves the inner handlers' ``PUSH_EXC_INFO`` rewritten to
        # ``POP_TOP`` by the single-``try`` finally path above, which the reader
        # cannot resolve once two ``SETUP_FINALLY`` point at it; synthesising
        # those over-nests, so 3+ levels keep their existing (already limited)
        # handling rather than being made worse.
        self.empty_body_setups = set()
        if len(blocks) == 1:
            for start, target in list(blocks):
                start_idx = by_offset.get(start)
                target_idx = by_offset.get(target)
                if start_idx is None or target_idx is None:
                    continue
                for h_idx in range(start_idx + 1, target_idx):
                    if self.raw[h_idx].opname != 'PUSH_EXC_INFO':
                        continue
                    h_off = self.raw[h_idx].offset
                    if h_off in claimed:
                        continue
                    if not self._is_finally_copy(start_idx, h_idx):
                        continue
                    claimed.add(h_off)
                    blocks.append((start, h_off))
                    # The inner body is empty, so its ``POP_BLOCK`` has no
                    # instruction to anchor on -- it is emitted right after the
                    # synthesised ``SETUP_FINALLY`` instead.
                    self.empty_body_setups.add((start, h_off))
                    break
        elif not blocks:
            # A *standalone* ``try``/``finally`` whose body is empty --
            # ``try: return X`` ... ``finally: C`` -- leaves no body entry at
            # all: the protected range has no instructions in it, so CPython
            # records only the clause's cleanup entry, the second copy of ``C``
            # guarded by a bare ``COPY``/``POP_EXCEPT``/``RERAISE`` stub.  With
            # no body entry the whole ``try`` disappears and ``C`` is emitted
            # twice as straight-line code.  Recover the block from that copy,
            # the same way the nested case above is recovered.
            for entry in entries:
                s_idx = by_offset.get(entry.start)
                t_idx = by_offset.get(entry.target)
                if s_idx is None or t_idx is None:
                    continue
                if self.raw[s_idx].opname != 'PUSH_EXC_INFO':
                    continue
                if self.raw[t_idx].opname != 'COPY':
                    continue
                if entry.target in self.with_targets:
                    continue
                begins = self._finally_copy_start(s_idx)
                if begins is None:
                    continue
                start_off = self.raw[begins].offset
                blocks.append((start_off, entry.start))
                self.empty_body_setups.add((start_off, entry.start))
                break
        setups = self._place_block_setups(entries, blocks)
        self.try_closes = closes
        self._analyse_handlers()
        self._redirect_handler_epilogues()
        self._place_block_closes(setups, closes)
        for end, target in self.name_closes.items():
            closes[end] = target
        return setups, closes

    def _is_finally_copy(self, start_idx, h_idx):
        """True when the handler at index *h_idx* is a bare ``finally`` handler
        whose body duplicates the inline clause starting at index *start_idx*.

        Used to recover a nested ``try``/``finally`` whose protected body is
        empty: the clause is emitted inline at *start_idx* and copied verbatim
        into the handler, so that copy is the only trace the inner ``try``
        leaves.
        """
        raw = self.raw
        n = len(raw)
        j = h_idx + 1
        body = []
        while j < n and raw[j].opname != 'RERAISE':
            body.append(raw[j])
            j += 1
        if not body or j >= n or raw[j].opname != 'RERAISE':
            return False
        if start_idx + len(body) > n:
            return False
        for k, ins in enumerate(body):
            other = raw[start_idx + k]
            if other.opname != ins.opname or other.argval != ins.argval:
                return False
        return True

    def _finally_copy_start(self, h_idx):
        """Index where the inline copy of the clause at *h_idx* begins.

        *h_idx* indexes the ``PUSH_EXC_INFO`` of a ``finally`` handler.  The
        clause is emitted twice -- once inline, just before the statement that
        leaves the block, and again in the handler -- so the earlier copy is
        found by matching the handler's body backwards.

        An empty clause (``finally: pass``) has no copy to match, and returns
        ``None``: the clause cannot change behaviour, so leaving the exit as
        straight-line code is both correct and simpler than synthesising a
        ``try`` around it.  Anchoring on the instruction before the handler
        would land in the middle of the exit sequence and drop its value.
        """
        raw = self.raw
        j = h_idx + 1
        body = []
        while j < len(raw) and raw[j].opname != 'RERAISE':
            body.append(raw[j])
            j += 1
        if not body or j >= len(raw) or raw[j].opname != 'RERAISE':
            return None
        width = len(body)
        for start in range(h_idx - width, -1, -1):
            if all(raw[start + k].opname == body[k].opname
                   and raw[start + k].argval == body[k].argval
                   for k in range(width)):
                return start
        return None

    def _place_block_setups(self, entries, blocks):
        """Map each ``SETUP_FINALLY`` offset to the handlers it opens.

        The table splits a ``try`` body at every nested block, so an outer
        ``try`` shows up as a run of entries whose handlers sit further out:
        the innermost handler owns the first span and the outer one picks up
        where that span ends.  3.9 opened both blocks before the first
        statement instead, so an entry whose predecessor's region ends exactly
        where it begins, and whose handler lies inside it, moves back to that
        predecessor's start.  Handlers are listed outermost first, which is the
        order 3.9 pushed the ``SETUP_FINALLY`` instructions in.
        """
        setups = {}
        for start, target in blocks:
            begins = start
            for entry in entries:
                if entry.target == target or entry.end != start:
                    continue
                if start <= entry.target < target:
                    begins = min(begins, entry.start)
            setups.setdefault(begins, []).append(target)
        for targets in setups.values():
            targets.sort(reverse=True)
        return setups

    def _offset_index(self, offset):
        """Index of the instruction at *offset*, or ``None``."""
        for index, raw in enumerate(self.raw):
            if raw.offset == offset:
                return index
            if raw.offset > offset:
                return None
        return None

    def _place_block_closes(self, setups, closes):
        """Anchor each ``POP_BLOCK`` to the instruction it must follow.

        ``co_exceptiontable`` records a half-open range, so ``entry.end`` is the
        offset just past the region 3.9 closed with ``POP_BLOCK``.  That offset
        is often one this pass removed -- the epilogue the compiler duplicated --
        and it is just as often the first instruction of whatever followed
        the region, so the close always goes on the last instruction *inside*
        it, skipping any that this pass dropped.
        """
        raw_list = self.raw
        entries = _exception_entries(self.code)
        for begins, targets in setups.items():
            for target in targets:
                self._place_one_close(entries, raw_list, begins, target,
                                      closes)
        for key in [k for k in closes if k in self.with_closes]:
            del closes[key]

    def _place_one_close(self, entries, raw_list, start, target, closes):
        # A region interrupted by a nested block -- a ``with`` or another
        # ``try`` -- comes back as several spans sharing this handler, and
        # 3.9 closed the block once, after the last of them.  Only the spans
        # that begin before the nested block's own handler do; the ones
        # after it are that handler's unwinding code, which the table sends
        # here as well.
        nested = [e.target for e in entries
                  if e.target != target and start < e.target <= target]
        limit = min(nested) if nested else target
        spans = [e for e in entries
                 if e.target == target and start <= e.start < limit]
        if not spans:
            return
        end = max(e.end for e in spans)
        index = self._offset_index(end)
        if index is None:
            index = len(raw_list)
        while index > 0 and raw_list[index - 1].offset in self._drops:
            index -= 1
        if index == 0:
            return
        close_at = raw_list[index - 1].offset
        if close_at in closes or close_at in self.with_closes:
            return
        closes[close_at] = end

    #: Opcodes that may build the exception type in front of ``CHECK_EXC_MATCH``.
    _TYPE_LOADS = frozenset((
        'LOAD_GLOBAL', 'LOAD_NAME', 'LOAD_FAST', 'LOAD_DEREF', 'LOAD_ATTR',
        'BUILD_TUPLE',
    ))

    def _is_finally_handler(self, raw_list, index) -> bool:
        """True when the handler at *index* belongs to a ``finally`` clause.

        A ``finally`` handler runs a copy of the clause and re-raises; it never
        tests the exception type.  The only ``except`` clause without a type
        test is the bare ``except:``, and 3.11 marks that one with a
        ``POP_TOP`` right behind the ``PUSH_EXC_INFO`` -- the triple 3.9 used
        to pop there.  A ``with`` block unwinds through its own handler, which
        starts with ``WITH_EXCEPT_START``.

        3.9 wrote a ``finally`` handler as the clause copy followed by a bare
        ``RERAISE``, with no ``DUP_TOP`` in front of it, so the handler has to
        be left alone: rewriting it as a bare ``except`` would turn the clause
        into an ``except`` body and read the inline copy as an ``else``.
        """
        n = len(raw_list)
        j = index + 1
        if j < n and raw_list[j].opname in ('POP_TOP', 'WITH_EXCEPT_START'):
            # The bare ``except:`` of 3.11, or a ``with`` block's own handler.
            return False
        while j < n:
            opname = raw_list[j].opname
            if opname == 'CHECK_EXC_MATCH':
                return False
            if opname == 'RERAISE':
                return True
            if opname in ('PUSH_EXC_INFO', 'SETUP_FINALLY', 'SETUP_EXCEPT',
                          'CHECK_EG_MATCH', 'WITH_EXCEPT_START'):
                return False
            j += 1
        return False

    def _analyse_handlers(self):
        """Rewrite the 3.11 handler dispatch into the 3.9 ``DUP_TOP`` shape.

        3.11 tests the running exception with ``CHECK_EXC_MATCH`` and branches on
        the boolean that leaves behind, so the type test and the dispatch are two
        instructions.  3.9 branched on the type directly, which left the
        exception duplicated under it: every handler therefore began with
        ``DUP_TOP`` and then cleared the triple it had duplicated.

        Only the first handler of a chain still carries a ``PUSH_EXC_INFO``; the
        rest are reached by the dispatch jump alone, so the duplicate has to be
        re-inserted in front of each of them.  ``except E as name`` is worse --
        3.11 binds the name straight onto the stack and protects the body with a
        nested table entry whose target is the implicit ``finally`` that unbinds
        it, where 3.9 wrote that nesting as an explicit ``SETUP_FINALLY``.
        """
        raw_list = self.raw
        by_offset = {raw.offset: n for n, raw in enumerate(raw_list)}
        before = self.try_before
        replace = self.try_replace
        entries = _exception_entries(self.code)
        for entry in entries:
            index = by_offset.get(entry.target)
            if index is None or raw_list[index].opname != 'PUSH_EXC_INFO':
                continue
            self._handler_heads.add(entry.target)
            if self._is_finally_handler(raw_list, index):
                # A ``finally`` handler is not a clause of an ``except`` chain:
                # it runs the clause and re-raises.  3.9 wrote it without the
                # ``DUP_TOP`` the reader uses to recognise a clause, so it is
                # left as it is.
                continue
            first = True
            while True:
                probe = index + 1
                while probe < len(raw_list) \
                        and raw_list[probe].opname in self._TYPE_LOADS:
                    probe += 1
                if probe >= len(raw_list) \
                        or raw_list[probe].opname != 'CHECK_EXC_MATCH':
                    # ``except:`` -- 3.9 spelled the triple pop with no test.
                    # The count is three even though 3.11 leaves a single
                    # ``POP_TOP`` here: the other two clear the exception
                    # triple 3.9 kept on the stack for the type test it no
                    # longer performs, and the reader's stack model needs the
                    # full three to see the clause body start where it does.
                    replace[raw_list[index].offset] = [
                        ('POP_TOP', None, None),
                        ('POP_TOP', None, None),
                        ('POP_TOP', None, None)]
                    break
                dispatch = probe + 1
                if dispatch >= len(raw_list) \
                        or not raw_list[dispatch].opname.startswith('POP_JUMP'):
                    break
                target = int(raw_list[dispatch].argval)
                head = raw_list[index].offset
                if first:
                    replace[head] = [('DUP_TOP', None, None)]
                    first = False
                else:
                    before[head] = [('DUP_TOP', None, None)]
                replace[raw_list[probe].offset] = [
                    ('JUMP_IF_NOT_EXC_MATCH', None, target)]
                bound = raw_list[dispatch + 1] \
                    if dispatch + 1 < len(raw_list) else None
                if bound is not None and bound.opname in _STORE_OPS:
                    replace[raw_list[dispatch].offset] = []
                    before[bound.offset] = [('POP_TOP', None, None)]
                    body = raw_list[dispatch + 2] \
                        if dispatch + 2 < len(raw_list) else None
                    tail: List[Tuple[str, Any, Any]] = [('POP_TOP', None, None)]
                    if body is not None:
                        cleanup = self._name_cleanup(entries,
                                                     raw_list[dispatch].offset,
                                                     body)
                        if cleanup is not None:
                            tail.append(('SETUP_FINALLY', None, cleanup))
                            body_end = self._name_body_end(entries, body)
                            if body_end is None:
                                # An empty handler body closes the implicit
                                # block straight away.
                                tail.append(('POP_BLOCK', None, None))
                            else:
                                self.name_closes[body_end] = cleanup
                        before[body.offset] = tail
                else:
                    replace[raw_list[dispatch].offset] = [
                        ('POP_TOP', None, None), ('POP_TOP', None, None)]
                index = by_offset.get(target)
                if index is None or raw_list[index].opname == 'RERAISE':
                    break
        for raw in raw_list:
            if raw.opname == 'RERAISE':
                replace[raw.offset] = [('RERAISE', None, None)]

    def _redirect_handler_epilogues(self):
        """Drop the copies of the ``return None`` epilogue 3.11 duplicated.

        3.11 parks a copy of the function epilogue at the end of the protected
        region and another inside every handler, so a handler that simply
        swallowed the exception ended in ``return None`` and a body that ran to
        completion returned early.  3.9 had a single epilogue and let both the
        body and the clause fall through to it, which is what the reader
        recognises as a ``try`` that simply continues.

        Only the implicit ``None`` return is folded -- one that returns a value
        of its own keeps its ``RETURN_VALUE``.
        """
        raw_list = self.raw
        by_offset = {raw.offset: n for n, raw in enumerate(raw_list)}
        entries = _exception_entries(self.code)
        heads = sorted(e.target for e in entries
                       if by_offset.get(e.target) is not None
                       and raw_list[by_offset[e.target]].opname == 'PUSH_EXC_INFO')
        for head in heads:
            index = by_offset[head]
            # The copy belongs to the region in front of this handler, so the
            # search stops at the handler before it -- whose own epilogue and
            # body are none of this block's business.
            earlier = [h for h in heads if h < head]
            floor = by_offset[max(earlier)] if earlier else 0
            step = self._return_none_at(index - 1)
            probe = index - 1
            while step is None and probe > floor:
                probe -= 1
                step = self._return_none_at(probe)
            if step is not None:
                self._drop_return_none(probe)
            # Every clause of the chain carries its own copy; 3.9 reached the
            # single one past the chain from all of them.
            for step in self._handler_epilogues(by_offset, index):
                self._drop_return_none(step)

    def _drop_return_none(self, index):
        """Drop the ``return None`` pair starting at *index*, if that is one."""
        step = self._return_none_at(index)
        if step is None:
            return
        self._drops.add(self.raw[step].offset)
        if self.raw[step].opname == 'LOAD_CONST':
            self._drops.add(self.raw[step + 1].offset)

    def _handler_epilogues(self, by_offset, index):
        """Where each clause of the chain starting at *index* returns ``None``.

        3.11 duplicates the function epilogue per clause and parks each copy at
        the end of that clause's body, so the chain is walked clause by clause
        through the dispatch jumps rather than through the table -- the copies
        sit outside the ranges the table records.  A clause's body starts
        *after* its own dispatch jump, and the next clause begins at the target
        of that jump, so one forward scan per clause finds both.
        """
        raw_list = self.raw
        found = []
        seen = set()
        start = index
        while start is not None and 0 <= start < len(raw_list) \
                and start not in seen:
            seen.add(start)
            nxt = None
            probe = start
            while probe < len(raw_list):
                opname = raw_list[probe].opname
                if opname == 'RERAISE':
                    break
                if opname == 'CHECK_EXC_MATCH':
                    dispatch = probe + 1
                    if dispatch < len(raw_list) \
                            and raw_list[dispatch].opname.startswith('POP_JUMP'):
                        nxt = self._next_handler(dispatch, by_offset)
                        probe = dispatch + 1
                        continue
                    break
                if opname in _JUMP_OPS or opname.startswith('POP_JUMP'):
                    break
                step = self._return_none_at(probe)
                if step is not None:
                    found.append(step)
                    break
                probe += 1
            start = nxt
        return found

    def _return_none_at(self, index):
        """Index of the implicit ``return None`` at *index*, or ``None``.

        3.12 returns the constant without loading it first, so the pair is one
        instruction wide; 3.11 loads it and returns in two.  A return of a value
        of its own is left alone.
        """
        raw_list = self.raw
        if index >= len(raw_list):
            return None
        if raw_list[index].opname == 'RETURN_CONST' \
                and raw_list[index].argval is None:
            return index
        if raw_list[index].opname == 'LOAD_CONST' \
                and raw_list[index].argval is None \
                and index + 1 < len(raw_list) \
                and raw_list[index + 1].opname in ('RETURN_VALUE', 'RETURN_CONST'):
            return index
        return None

    def _next_handler(self, index, by_offset):
        """Offset of the clause a failed dispatch at *index* jumps to."""
        raw_list = self.raw
        target = raw_list[index].argval
        if target is None:
            return None
        return by_offset.get(int(target))

    def _name_cleanup(self, entries, dispatch, body):
        """Offset of the implicit ``finally`` that unbinds ``except ... as name``.

        3.11 emits the name cleanup twice -- once inline where the handler body
        ends, once in a handler of its own -- and protects each copy with its own
        table entry.  3.9 wrote the same nesting as a ``SETUP_FINALLY`` in front
        of the body, so the setup branched to the handler copy.

        The handler copy is the target of the entry that covers the body, so
        that is where the synthesised ``SETUP_FINALLY`` has to point.  A body
        the compiler left empty has no entry of its own; there the copy is the
        first region the table mentions past the dispatch.
        """
        fallback = None
        for entry in entries:
            if not entry.lasti or entry.start <= dispatch:
                continue
            if body is not None and entry.start == body.offset:
                return entry.target
            if fallback is None:
                fallback = entry.start
        return fallback

    def _name_body_end(self, entries, body):
        """Offset of the last instruction of an ``except ... as name`` body.

        The body is the span the table protects between the binding and the
        inline name cleanup, so the close of the implicit block goes on its last
        instruction -- the rotation that follows it belongs to the exit
        sequence, not to the body.
        """
        for entry in entries:
            if entry.start == body.offset and entry.lasti:
                return self._last_offset_before(entry.end)
        return None

    def _last_offset_before(self, end):
        """Offset of the last instruction that starts before *end*."""
        best = None
        for raw in self.raw:
            if raw.offset < end and (best is None or raw.offset > best):
                best = raw.offset
        return best

    def _is_method_loader(self, raw):
        """True when *raw* loads a bound method rather than a plain attribute.

        3.11 has a dedicated ``LOAD_METHOD``, and its ``LOAD_ATTR`` argument is
        the bare name index with no flag bits at all.  3.12 dropped the opcode
        and encoded the same intent by shifting the name index left by one, so
        bit 0 of the argument marks the load as a method load.
        """
        if raw.opname == 'LOAD_METHOD':
            return True
        if raw.opname == 'LOAD_SUPER_ATTR':
            return bool(raw.arg is not None and raw.arg & 1)
        if self.attr_method_bit is None:
            return False
        if raw.opname != 'LOAD_ATTR' or raw.arg is None:
            return False
        return bool(raw.arg & (1 << self.attr_method_bit))

    def analyse(self):
        """Decide, per call, whether it is a plain, method or decorator call.

        3.11 records the intent in the instruction stream rather than leaving
        it to be inferred, with a dedicated ``LOAD_METHOD``.  Such a loader
        pushes the receiver and the attribute, and the call it
        feeds is the first one whose argument count matches the operands
        stacked *directly* on top of it -- ``d.append(str(x))`` runs ``str(x)``
        first, and only the second ``CALL`` reaches back to the loader.
        ``KW_NAMES`` names the keywords of the next call.

        A decorator is recognised from the shape rather than a flag: 3.11 calls
        ``deco`` by leaving the decorator *below* the function object on the
        stack and then issuing ``CALL 0``, so the ``self_or_null`` slot the
        call consumes is the freshly made function and the callable is the
        decorator.  3.9 spelled the same thing ``CALL_FUNCTION 1``, passing the
        function as an ordinary argument.

        Loaders nest: the argument of ``f.write('\\n'.join(results))`` is
        itself a method call, so the inner loader is pushed while the outer
        one is still waiting for its call.  Each loader therefore keeps its own
        depth -- how many stack slots sit above it -- and every pushed value
        counts against all of them.
        """
        shape = _Shape()
        pending_kw = None
        pending_depths = []
        just_made = False
        for index, raw in enumerate(self.raw):
            opname = raw.opname
            if opname == 'KW_NAMES':
                pending_kw = self.code.co_consts[raw.arg]
                continue
            if opname in DROPPED:
                continue
            if opname == 'MAKE_FUNCTION':
                just_made = True
                continue
            if self._is_method_loader(raw):
                # The new method slot sits on top of every loader that is
                # still waiting for its call, so each of them is one slot
                # further from its own call.
                for position in range(len(pending_depths)):
                    pending_depths[position] += 1
                pending_depths.append(0)
                shape.methods.add(raw.offset)
                just_made = False
                continue
            if opname in ('CALL', 'CALL_KW'):
                argc = raw.arg or 0
                is_kw_inline = opname == 'CALL_KW'
                has_kw = is_kw_inline or pending_kw is not None
                if just_made and not has_kw and argc == 0 \
                        and self._is_decorator_call(index):
                    shape.decorators.add(raw.offset)
                    del pending_depths[:]
                else:
                    # 3.13/3.14's ``CALL_KW`` pops the keyword-name tuple from
                    # the stack, so it sits one slot above the arguments; the
                    # 3.11/3.12 ``KW_NAMES`` takes the tuple as an operand and
                    # leaves the stack alone.
                    is_method = bool(pending_depths) \
                        and pending_depths[-1] == argc + (1 if is_kw_inline else 0)
                    if has_kw:
                        name = 'CALL_METHOD_KW' if is_method \
                            else 'CALL_FUNCTION_KW'
                        shape.kw_names[raw.offset] = pending_kw
                    else:
                        name = 'CALL_METHOD' if is_method else 'CALL_FUNCTION'
                    shape.calls[raw.offset] = name
                    # A ``CALL`` that closes a nested argument expression --
                    # the ``str(x)`` of ``d.append(str(x))`` -- is not the
                    # loader's call, but the loader is still waiting for one.
                    # Keep following the stack instead of dropping the
                    # association, so the outer ``CALL`` is still recognised.
                    #
                    # The effect is written out rather than read from
                    # ``dis``: 3.11 splits a call over ``PRECALL argc``
                    # (``-argc``, skipped as bookkeeping) and ``CALL``
                    # (``-1``), while 3.12 puts the whole ``-(argc + 1)`` on
                    # ``CALL``.  The pair always nets ``-(argc + 1)``.
                    if is_method:
                        pending_depths.pop()
                    delta = argc + (2 if is_kw_inline else 1)
                    for position in range(len(pending_depths)):
                        pending_depths[position] -= delta
                just_made = False
                pending_kw = None
                continue
            if opname in ('CALL_FUNCTION_EX',) or opname in _STORE_OPS \
                    or opname in _JUMP_OPS or opname.startswith('POP_JUMP'):
                del pending_depths[:]
                just_made = False
                continue
            for position in range(len(pending_depths)):
                pending_depths[position] += _stack_effect(raw)
            # A decorator call has nothing between ``MAKE_FUNCTION`` and the
            # ``CALL``: any other operand means the function is an ordinary
            # argument, as it is for a comprehension's own call.
            just_made = False
        return shape

    def _is_decorator_call(self, index):
        """True when the ``CALL`` at *index* applies a decorator.

        Walking back over the operands ``MAKE_FUNCTION`` may have consumed --
        defaults, keyword defaults, annotations and the closure tuple -- leaves
        whatever was pushed *before* the function object.  If that is a value
        rather than the ``NULL`` a plain call needs, the call is the decorator
        being handed the function.
        """
        raw_list = self.raw
        position = index - 1
        while position >= 0:
            raw = raw_list[position]
            opname = raw.opname
            if opname in DROPPED or opname in _MAKE_OPERANDS:
                position -= 1
                continue
            if opname == 'PUSH_NULL':
                return False
            if opname in _NULL_BIT_OPS and raw.arg is not None and raw.arg & 1:
                return False
            return True
        return False

    def run(self):
        code = self.code
        shape = self.analyse()
        runs = self._store_runs()
        out = []
        raw_list = self.raw
        by_offset = {raw.offset: n for n, raw in enumerate(raw_list)}
        close_merges = self._close_merge_offsets()
        tails = getattr(self, '_tails_at_merge', {})
        ignore_drops = getattr(self, '_tail_offsets', frozenset())
        index = 0
        while index < len(raw_list):
            raw = raw_list[index]
            # Re-emit a saved tail at its merge point.  3.12 parks the code
            # that follows a module level try/except *before* the handler, so
            # it has to be moved after it; running it through the same
            # translation as the main stream is what keeps ``CALL``,
            # ``MAKE_FUNCTION`` and ``RETURN_CONST`` in the 3.9 shape.
            tail = tails.get(raw.offset)
            if tail:
                positions = [by_offset[r.offset] for r in tail
                             if r.offset in by_offset]
                k = 0
                while k < len(positions):
                    nxt = self._translate_step(positions[k], out, runs, shape,
                                               close_merges, ignore_drops)
                    k += 1
                    while k < len(positions) and positions[k] < nxt:
                        k += 1
            index = self._translate_step(index, out, runs, shape, close_merges)
        return out

    def _close_merge_offsets(self):
        """Map each protected-region close offset to the point past its handler.

        3.9 ended a ``try`` body with ``POP_BLOCK`` followed by a forward jump
        over the handler; 3.11/3.12 record the region in the exception table
        instead, so the close offset (``entry.end``) has to grow the same skip
        jump here.
        """
        if not self.try_closes:
            return {}
        by_end = {}
        for entry in _exception_entries(self.code):
            by_end.setdefault(entry.end, entry)
        merges = {}
        for close, end in self.try_closes.items():
            entry = by_end.get(end)
            if entry is not None:
                merges[close] = self._merge_offset(entry)
        return merges

    def _translate_step(self, index, out, runs, shape, close_merges,
                        ignore_drops=frozenset()):
        """Translate ``self.raw[index]`` into the 3.9 shape, appending to *out*.

        Returns the index to continue from; every path advances it, so the
        caller can drive the whole stream -- or a saved tail -- with it.
        *ignore_drops* names offsets whose ``_drops`` entry must be honoured
        only when the instruction is translated as part of the main stream
        (the tail re-emission), not when it is reached in place.
        """
        raw = self.raw[index]
        close_after = raw.offset in self.try_closes
        before = len(out)
        result = self._translate_instruction(
            index, out, runs, shape, close_merges, ignore_drops)
        if close_after and len(out) > before:
            # 3.9 closed the block straight after the last instruction of the
            # protected region.  The inline ``else``/``finally`` clause 3.11
            # kept in front of the handler follows right after it, and the
            # reader recovers the clause (and the resume point) from that gap.
            # The close is emitted here rather than inside the translation of
            # the instruction, because several opcodes are translated by a
            # branch of their own that never reaches the common tail.
            out.append(self._make(raw, 'POP_BLOCK', None, None, line_no=None))
        return result

    def _translate_instruction(self, index, out, runs, shape, close_merges,
                               ignore_drops=frozenset()):
        """Translate one instruction; see :meth:`_translate_step`."""
        code = self.code
        raw_list = self.raw
        raw = raw_list[index]
        opname = raw.opname
        loop_exit = self._loop_breaks.get(raw.offset)
        if loop_exit is not None:
            out.append(self._make(raw, 'JUMP_ABSOLUTE', loop_exit, loop_exit,
                                  synthetic_loop_exit=True))
            return index + 1
        if index in runs:
            return self._emit_store_run(index, runs[index], out)
        if opname == 'COPY':
            jump = self._or_pop_jump(index)
            if jump is not None:
                out.append(jump)
                return index + 3
        if raw.offset in self.try_before:
            out.extend(self._make(raw, op, a, v)
                       for op, a, v in self.try_before[raw.offset])
        async_target = self.async_with_setups.get(raw.offset)
        if async_target is not None:
            out.append(self._make(raw, 'SETUP_ASYNC_WITH', async_target,
                                  async_target, line_no=None))
        spec = self.comprehensions.get(raw.offset)
        if spec is not None:
            return self._lift_comprehension(index, spec, out)
        prefix = self.with_anchors.get(raw.offset)
        if prefix is not None:
            # 3.14's explicit ``__enter__``/``__exit__`` prefix collapses back
            # into the single 3.9 ``SETUP_WITH``; everything up to and
            # including the ``__enter__`` call is consumed with it.
            target = self.with_setups[raw.offset]
            out.append(self._make(raw, 'SETUP_WITH', target, target,
                                  line_no=None))
            return index + prefix
        if raw.offset in self._drops and raw.offset not in ignore_drops:
            return index + 1
        if raw.offset in self.try_replace:
            out.extend(self._make(raw, op, a, v)
                       for op, a, v in self.try_replace[raw.offset])
            return index + 1
        following = raw_list[index + 1] if index + 1 < len(raw_list) else None
        if opname == 'RETURN_CONST':
            # 3.12 returns a constant without pushing it first; 3.9 always
            # loaded the value and then returned, so the load is re-inserted.
            out.append(self._make(raw, 'LOAD_CONST', raw.arg,
                                  code.co_consts[raw.arg]))
            out.append(self._make(raw, 'RETURN_VALUE', None, None,
                                  line_no=None))
            return index + 1
        if opname == 'LOAD_SMALL_INT':
            # 3.14 folds small integer constants into their own opcode.
            out.append(self._make(raw, 'LOAD_CONST', None, raw.argval,
                                  line_no=None))
            return index + 1
        if opname == 'LOAD_COMMON_CONSTANT':
            # 3.14 loads a handful of builtins the compiler knows about.  Only
            # ``AssertionError`` has a dedicated 3.9 opcode the reader uses to
            # rebuild ``assert``; the rest are ordinary name loads, not
            # constants (``tuple`` must not unparse as ``<class 'tuple'>``).
            const = _common_constant(raw.arg)
            name = getattr(const, '__name__', None)
            if name == 'AssertionError':
                out.append(self._make(raw, 'LOAD_ASSERTION_ERROR', None, None,
                                      line_no=None))
            elif name:
                opcode = 'LOAD_GLOBAL' if code.co_flags & 0x1 else 'LOAD_NAME'
                out.append(self._make(raw, opcode, None, name, line_no=None))
            else:
                out.append(self._make(raw, 'LOAD_CONST', None, const,
                                      line_no=None))
            return index + 1
        if opname == 'LOAD_LOCALS':
            # 3.14 uses this to capture a class body's namespace for inline
            # annotation scopes.  Those scopes are compiler machinery, so the
            # assignment it feeds is stripped with the other class artifacts.
            out.append(self._make(raw, 'LOAD_CONST', None, None, line_no=None))
            return index + 1
        if opname == 'CONVERT_VALUE':
            # The conversion is folded into the ``FORMAT_*`` that consumes the
            # value.  Remember it until then: a ``FORMAT_WITH_SPEC`` formats
            # its spec expression first, so the conversion is not necessarily
            # on the instruction right before it.
            self._pending_conversion = (index, raw.arg or 0)
            return index + 1
        if opname in ('FORMAT_SIMPLE', 'FORMAT_WITH_SPEC'):
            conversion = 0
            pending = self._pending_conversion
            if pending is not None:
                origin, value = pending
                if opname == 'FORMAT_WITH_SPEC' or index == origin + 1:
                    conversion = value
                    self._pending_conversion = None
            flags = conversion | (0x4 if opname == 'FORMAT_WITH_SPEC' else 0)
            out.append(self._make(raw, 'FORMAT_VALUE', flags, flags,
                                  line_no=None))
            return index + 1
        if opname in DROPPED or opname == 'PUSH_NULL':
            return index + 1
        if opname == 'SWAP':
            if raw.offset in self.with_swaps:
                # The 3.9 block close was folded into this rotation.  Emit
                # the missing ``POP_BLOCK`` first so the reader still sees
                # a balanced block, then rotate as usual.
                out.append(self._make(raw, 'POP_BLOCK', None, None,
                                      line_no=None))
            if following is not None and following.opname == 'COPY' \
                    and following.arg == raw.arg:
                # A chained comparison duplicates the shared operand with
                # SWAP/COPY; 3.9 spells the same stack effect as
                # DUP_TOP followed by ROT_THREE.
                out.append(self._make(raw, 'DUP_TOP', None, None))
                out.append(self._make(following, 'ROT_THREE', None, None))
                return index + 2
            out.append(self._make(raw, SWAP_TO_ROT.get(raw.arg, 'ROT_TWO'),
                                  None, None))
            return index + 1
        if opname == 'COPY':
            if raw.arg == 1:
                out.append(self._make(raw, 'DUP_TOP', None, None))
            return index + 1
        if opname == 'SEND':
            # ``yield from`` and ``await`` are a loop in 3.11 but a single
            # opcode in 3.9:
            #   SEND / YIELD_VALUE / RESUME / JUMP_BACKWARD_NO_INTERRUPT
            # The back edge lands on the ``SEND``, so the replacement takes
            # the ``SEND`` offset and every jump stays resolvable.  Only the
            # loop itself is dropped: whatever consumes the result -- the
            # ``POP_TOP`` of a statement form, the ``STORE_*`` of an
            # assignment -- is the real 3.9 instruction and is left alone.
            if following is not None and following.opname == 'YIELD_VALUE':
                end = self._skip_send_loop(index)
                yield_from = self._make(raw, 'YIELD_FROM', None, None)
                # The only jump that ever targeted this offset was the
                # loop's own back edge, which the collapse dropped.  The
                # raw flag would still read the collapsed ``YIELD_FROM``
                # as the start of a new statement and split a ``with``
                # body's teardown in half.
                yield_from.is_jump_target = False
                out.append(yield_from)
                return end
        if opname == 'BEFORE_WITH':
            target = self.with_setups.get(raw.offset)
            if target is None:
                return index + 1
            out.append(self._make(raw, 'SETUP_WITH', target, target,
                                  line_no=None))
            return index + 1
        if raw.offset in self.supers:
            # 3.12 folded the ``super()`` call into the attribute load, so
            # the call has to grow again in front of it and the operand
            # ``LOAD_SUPER_ATTR`` pushed for it has to go.
            argc, is_method = self.supers[raw.offset]
            out.append(self._make(raw, 'CALL_FUNCTION', argc, argc,
                                  line_no=None))
            out.append(self._make(
                raw, 'LOAD_METHOD' if is_method else 'LOAD_ATTR',
                raw.arg >> 2, raw.argval,
            ))
            return index + 1
        if raw.offset in self.try_setups:
            for target in self.try_setups[raw.offset]:
                out.append(self._make(raw, 'SETUP_FINALLY', raw.offset,
                                      target, line_no=None))
                if (raw.offset, target) in self.empty_body_setups:
                    # The inner ``try`` body is empty, so 3.9 closed it with a
                    # ``POP_BLOCK`` right after the ``SETUP_FINALLY``.
                    out.append(self._make(raw, 'POP_BLOCK', None, None,
                                          line_no=None))
        if raw.offset in self.with_closes:
            # 3.9 closed the ``with`` block right before the implicit
            # ``__exit__`` call, so the close goes in front of the operands the
            # call starts with.  The operands themselves stay: the call needs
            # three of them, and dropping one would leave it a call short.
            out.append(self._make(raw, 'POP_BLOCK', None, None, line_no=None))
        if opname in POP_JUMP_ALIASES:
            name = POP_JUMP_ALIASES[opname]
        elif opname in ('JUMP_BACKWARD', 'JUMP_BACKWARD_NO_INTERRUPT',
                        'JUMP'):
            name = 'JUMP_ABSOLUTE'
        elif opname == 'BINARY_OP':
            out.append(self._make(raw, _nb_opcode(raw.arg), None, None,
                                  line_no=None))
            return index + 1
        elif opname in ('BINARY_SLICE', 'STORE_SLICE'):
            # 3.12 folded ``BUILD_SLICE 2`` and the subscript that consumes the
            # slice into a single opcode.  Only the two-argument form was
            # folded -- a three-argument slice still compiles to
            # ``BUILD_SLICE 3`` followed by ``BINARY_SUBSCR``.  Unfolding it
            # matters: the stock reader takes its slice operands from the
            # ``BUILD_SLICE``, so without this the bounds and the container are
            # silently dropped and ``s[i:j]`` decompiles to whatever happened to
            # be on the stack (usually ``None``).
            out.append(self._make(raw, 'BUILD_SLICE', 2, 2, line_no=None))
            out.append(self._make(
                raw,
                'BINARY_SUBSCR' if opname == 'BINARY_SLICE' else 'STORE_SUBSCR',
                None, None,
            ))
            return index + 1
        elif opname == 'CALL_INTRINSIC_1':
            # 3.12 folded a few standalone opcodes into one intrinsic call.
            # Unmapped intrinsics belong to machinery the stock reader handles
            # elsewhere (a generator wrapper, a type-parameter builder), so
            # they are left for the rest of the pipeline to skip.
            intrinsic = _intrinsic_1_opcode(raw.arg)
            if intrinsic is None:
                return index + 1
            out.append(self._make(raw, intrinsic, None, None, line_no=None))
            return index + 1
        elif opname in ('LOAD_METHOD', 'LOAD_ATTR') \
                and raw.offset in shape.methods:
            name = 'LOAD_METHOD'
        elif opname in LOAD_FAST_ALIASES:
            name = LOAD_FAST_ALIASES[opname]
        elif opname in ('CALL', 'CALL_KW', 'CALL_FUNCTION_EX'):
            if raw.offset in shape.decorators:
                # 3.11 leaves the decorator *below* the function object and
                # issues ``CALL 0``, so the function is an ordinary argument
                # of the 3.9 call that consumes the decorator.
                out.append(self._make(raw, 'CALL_FUNCTION', 1, 1))
                return index + 1
            # 3.11 counts the ``self_or_null`` slot in the argument and pops
            # it together with the arguments; the 3.9 call opcodes count the
            # callable itself instead and pop it too, so the number carries
            # over unchanged.
            name = shape.calls.get(raw.offset, opname)
            names = shape.kw_names.get(raw.offset)
            if names is not None and names in code.co_consts:
                out.append(self._make(raw, 'LOAD_CONST',
                                      code.co_consts.index(names), names,
                                      line_no=None))
                out.append(self._make(raw, 'KW_NAMES', None, names,
                                      line_no=None))
        else:
            name = opname
        if name == 'NOP':
            return index + 1
        arg = raw.arg
        argval = _resolve(raw, code)
        if raw.offset in self._retarget:
            argval = self._retarget[raw.offset]
        if opname == 'CALL_FUNCTION_EX' and self.version >= (3, 14):
            # 3.14 dropped the oparg: the trailing ``PUSH_NULL`` marks a plain
            # ``f(*args)``, while its absence means a keyword mapping follows
            # the positional tuple.
            previous = raw_list[index - 1] if index else None
            arg = argval = 0 if previous is not None \
                and previous.opname == 'PUSH_NULL' else 1
        if raw.offset in self.with_exits and self.version < (3, 14):
            # 3.12/3.13 count the already-bound ``__exit__`` itself in the
            # ``CALL`` argument, while 3.9 pops the method together with
            # its three ``None`` operands.  3.14 spells the call the 3.9 way.
            name = 'CALL_FUNCTION'
            arg = argval = (arg or 0) + 1
        if opname == 'MAKE_FUNCTION':
            self._push_qualname(raw, out)
        out.append(self._make(raw, name, arg, argval))
        return index + 1

    def _push_qualname(self, raw, out):
        """Re-insert the qualname operand that 3.11 dropped from ``MAKE_FUNCTION``.

        3.9 pushes the code object and *then* the qualname; 3.11+ keeps the
        qualname in ``co_qualname`` and pushes only the code object, so the
        stock decompiler would pop whatever follows as if it were the name.
        """
        if not out:
            return
        value = out[-1].argval
        if isinstance(value, _SyntheticComprehension):
            # A lifted comprehension already carries the name the stock reader
            # keys its node type off, and it is pushed separately.
            return
        if not hasattr(value, 'co_code'):
            return
        # 3.9 pushed the *plain* name of the nested code object, which for a
        # comprehension is ``<listcomp>`` and not the dotted ``co_qualname``.
        name = getattr(value, 'co_name', None)
        if name is None:
            return
        out.append(self._make(raw, 'LOAD_CONST', None, name,
                              line_no=None))

    def _emit_store_run(self, index, end, out):
        """Rebuild one parallel assignment in the 3.9 rotation idiom.

        3.11 pushes the right-hand values in source order and then stores the
        targets in reverse, which is the same net effect as 3.9's
        ``ROT_THREE``/``ROT_TWO`` followed by forward stores.  The rotations
        borrow the offset of the first store so that a jump aimed at the
        assignment still lands on its first instruction.
        """
        raw_list = self.raw
        anchor = raw_list[index]
        for name in ROT_PREFIX[end - index]:
            out.append(self._make(anchor, name, None, None))
        for slot in range(end - 1, index - 1, -1):
            raw = raw_list[slot]
            out.append(self._make(raw, raw.opname, raw.arg,
                                  _resolve(raw, self.code)))
        return end

    def _or_pop_jump(self, index):
        """Fold 3.12's three-instruction short circuit into 3.9's one.

        3.12 compiles ``a and b`` by duplicating ``a``, branching on the copy
        and discarding it, so the value that survives is the *original* rather
        than a re-pushed one.  3.9 expressed the same thing with a single
        ``JUMP_IF_FALSE_OR_POP``.  An ``if`` statement needs no duplicate, so
        only the ``COPY 1``-led form is folded.
        """
        raw_list = self.raw
        if index + 2 >= len(raw_list):
            return None
        copy, guard, discard = raw_list[index:index + 3]
        if copy.arg != 1:
            return None
        if guard.opname not in ('POP_JUMP_IF_FALSE', 'POP_JUMP_IF_TRUE'):
            return None
        if discard.opname != 'POP_TOP':
            return None
        suffix = '_FALSE' if guard.opname.endswith('FALSE') else '_TRUE'
        return self._make(copy, 'JUMP_IF%s_OR_POP' % suffix, guard.arg,
                          _resolve(guard, self.code))

    def _skip_send_loop(self, index):
        """Index just past the 3.11 loop that implements ``yield from``/``await``.

        The loop stops where the send finishes; the instruction there consumes
        the result and must survive, so ``POP_TOP`` is not part of it.
        """
        raw_list = self.raw
        cursor = index
        total = len(raw_list)
        while cursor < total:
            opname = raw_list[cursor].opname
            if opname == 'SEND':
                cursor += 1
                continue
            if opname in ('YIELD_VALUE', 'RESUME',
                          'JUMP_BACKWARD', 'JUMP_BACKWARD_NO_INTERRUPT',
                          'END_FOR', 'POP_ITER'):
                cursor += 1
                continue
            break
        return cursor

    def _store_runs(self):
        """Index ranges of the runs of stores that 3.9 spelled as rotations.

        3.11 compiles ``a, b, c = b, c, a`` by pushing ``b, c, a`` and then
        storing them in *reverse* order with no rotation at all; 3.9 rotated
        the stack and stored in forward order.  A run is only rewritable when
        it is short enough to have used rotations and is not the tail of a real
        container unpacking, so ``a, b, c = t`` keeps its ``UNPACK_SEQUENCE``.
        """
        raw_list = self.raw
        total = len(raw_list)
        runs = {}
        index = 0
        while index < total:
            if raw_list[index].offset in self._drops \
                    or raw_list[index].opname not in _STORE_OPS:
                index += 1
                continue
            end = index
            while end < total and raw_list[end].opname in _STORE_OPS \
                    and raw_list[end].offset not in self._drops:
                end += 1
            count = end - index
            before = raw_list[index - 1] if index else None
            if count in ROT_PREFIX and before is not None \
                    and before.opname not in _UNPACK_OPS \
                    and not _duplicates_for(before):
                runs[index] = end
            index = end
        return runs

    def _make(self, raw, opname, arg, argval, line_no=None,
              synthetic_loop_exit=False):
        """Build one 3.9 :class:`Instruction` standing in for *raw*."""
        if line_no is None:
            line_no = raw.starts_line
        return Instruction(
            offset=raw.offset,
            opcode=raw.opcode,
            opname=opname,
            arg=arg,
            argval=argval,
            argrepr=_repr_of(opname, arg, argval),
            line_no=line_no,
            is_jump_target=raw.offset in self.jump_targets,
            synthetic_loop_exit=synthetic_loop_exit,
        )


class _SyntheticComprehension(object):
    """A stand-in for the nested code object 3.12 no longer creates.

    Python 3.12 inlines list/set/dict comprehensions into the enclosing code
    object, so there is no ``<listcomp>`` object left to hand the stock
    decompiler.  This carries the *already translated* instruction list for
    the loop body plus the name the decompiler keys its node type off, which
    is all :meth:`Decompiler._build_comprehension` actually reads.

    ``co_code`` is a placeholder: the stock ``MAKE_FUNCTION`` handler only
    tests for its presence to recognise a nested code object, and
    :class:`TranslatingDisassembler` intercepts the object before any real
    disassembly would happen.
    """

    co_code = b''

    def __init__(self, name, instructions):
        self.co_name = name
        self.instructions = instructions

    def __repr__(self):
        return '<synthetic %s>' % self.co_name


class TranslatingDisassembler(object):
    """Stands in for :class:`bytecode2code.Disassembler` on 3.11 / 3.12."""

    def disassemble(self, code, show_lineno=True):
        if isinstance(code, _SyntheticComprehension):
            return code.instructions
        return Rewriter(code).run()

    def disassemble_to_str(self, code, show_header=True, show_lineno=True):
        return '\n'.join(
            ins.opname for ins in self.disassemble(code, show_lineno)
        )


class Decompiler311(Decompiler310):
    """3.9 decompiler fed with a 3.9 shaped view of 3.11 bytecode.

    3.11 kept 3.10's rotated ``while`` layout (the condition is re-evaluated at
    the bottom of the body and a conditional jump goes back to the *body*
    start), so the 3.10 shims are inherited rather than duplicated; only the
    instruction source differs.
    """

    #: ``Rewriter`` already removes the copied implicit returns, so the 3.10
    #: handler-tail shim must not run a second time.
    _copied_none_return = False

    def __init__(self):
        super().__init__()
        self.dis = TranslatingDisassembler()

    def _classify_jump(self, instructions, instr):
        """Only an actual jump can be a ``break``/``continue``.

        The stock implementation trusts its caller, which always passes the
        last instruction of a 3.9 ``if`` body -- where the compiler always
        closed the branch with a jump.  3.11 simply falls through to
        the merge point instead, so the same index can hold a ``POP_EXCEPT``
        or a store whose ``argval`` is a name or ``None``.
        """
        if instr.opname not in _JUMP_OPS:
            return None
        return super()._classify_jump(instructions, instr)

    def _collect_finally_body(
        self, code, instructions, try_end_idx: int, handler_start_idx: int
    ):
        """Recover the ``finally`` clause for 3.11/3.12.

        3.11/3.12 lay out finally blocks differently than 3.9:
        - The clause is emitted inline after the try body (not in the handler)
        - The handler contains a COPY of the clause
        - We need to skip both the inline clause AND the handler copy

        The key is to mark the handler copy as handled so it's not re-emitted.
        """
        if handler_start_idx <= try_end_idx or handler_start_idx >= len(instructions):
            return [], None

        start = try_end_idx + 1

        # 3.9 uses a jump to close the inline copy; 3.11/3.12 don't always
        if start < len(instructions) and instructions[start].opname in ("JUMP_FORWARD", "JUMP_ABSOLUTE"):
            # Inline copy closed with jump; resume after the handler
            end = start
            # Mark the handler copy as handled
            handler_end = self._handler_end(instructions, handler_start_idx)
            self._handled_ranges.append((handler_start_idx, handler_end))
            return [], handler_end

        # Collect the inline finally clause
        length = self._finally_clause_length(instructions, handler_start_idx)
        end = min(handler_start_idx, start + length)

        if length or instructions[start].opname != "RETURN_VALUE":
            resume = end
        else:
            # Return after block pop is body's own, handler follows as in 3.9
            resume = None

        # Mark the handler copy as handled to prevent re-emission
        handler_end = self._handler_end(instructions, handler_start_idx)
        self._handled_ranges.append((handler_start_idx, handler_end))

        if end <= start:
            return [], resume

        body = self._emit_statements(
            code, instructions, is_module=False, start=start, end=end,
            out_stack=[],
        )
        # Strip trailing pass/raise/return None that belong to the clause setup
        while body and (
            isinstance(body[-1], (ast.Pass, ast.Raise)) or _is_bare_return(body[-1])
        ):
            body.pop()
        return body, resume

    def _handler_end(
        self, instructions, handler_start_idx: int
    ) -> int:
        """Index just past the handler.

        The handler ends at the re-raise or at whatever leaves the function.
        """
        n = len(instructions)
        for j in range(handler_start_idx, n):
            if instructions[j].opname in ("RERAISE", "RETURN_VALUE"):
                return j + 1
            if instructions[j].opname in ("SETUP_FINALLY", "SETUP_EXCEPT"):
                return j
        return n

    def _finally_clause_length(
        self, instructions, handler_start_idx: int
    ) -> int:
        """How many instructions the inline copy of a finally clause has.

        The copy ends at the re-raise that follows it.
        """
        n = len(instructions)
        if handler_start_idx >= n:
            return 0
        if instructions[handler_start_idx].opname == "RERAISE":
            return 0
        start = handler_start_idx
        while start < n and instructions[start].opname in self._BLOCK_NOISE:
            start += 1
        end = start
        while end < n and instructions[end].opname != "RERAISE":
            end += 1
        return end - start


def make_decompiler():
    return Decompiler311()
