import dis
import opcode
import ast
import sys
from contextlib import contextmanager
from typing import List, Dict, Any, Set, Tuple, Optional
from dataclasses import dataclass

from .disassembler import Disassembler, Instruction
from .errors import DecompilationError

#: Returned by :meth:`Decompiler._unwrap_assert_msg` when the instruction run it
#: was handed is not an ``assert`` after all, so the caller can back out instead
#: of inventing one.
_NOT_AN_ASSERT = object()


def _as_missing_bound(node):
    """``None`` for a slice bound the source omitted, else *node* unchanged.

    An omitted bound reaches the decompiler as ``LOAD_CONST None``, and an
    ``ast.Constant`` holding it unparses as a written-out ``None`` -- turning
    ``s[::-1]`` into ``s[None::-1]``, which is the same slice written the long
    way round.
    """
    if isinstance(node, ast.Constant) and node.value is None:
        return None
    return node


#: Opcodes whose operand is a target byte offset rather than a table index.
_JUMP_OPNAMES = frozenset((
    "JUMP_ABSOLUTE", "JUMP_FORWARD", "JUMP_BACKWARD", "JUMP",
    "POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE",
    "POP_JUMP_FORWARD_IF_FALSE", "POP_JUMP_FORWARD_IF_TRUE",
    "POP_JUMP_BACKWARD_IF_FALSE", "POP_JUMP_BACKWARD_IF_TRUE",
    "JUMP_IF_FALSE_OR_POP", "JUMP_IF_TRUE_OR_POP",
    "JUMP_IF_NOT_EXC_MATCH", "CHECK_EXC_MATCH", "FOR_ITER",
    "SEND", "SETUP_FINALLY", "SETUP_EXCEPT", "SETUP_WITH", "SETUP_ASYNC_WITH",
    "SETUP_LOOP", "SETUP_CLEANUP",
))


def _jump_target(instr) -> Optional[int]:
    """Byte offset an instruction jumps to, or ``None`` if it is not a jump.

    The disassembler reports the resolved absolute target as ``argval``, but
    ``None`` for a ``JUMP_IF_NOT_EXC_MATCH`` whose target is unresolved, and a
    plain integer for every instruction that is *not* a jump -- where the
    integer is an index into ``co_names``/``co_consts``.  Callers must not
    coerce that to a target.
    """
    if instr.opname not in _JUMP_OPNAMES:
        return None
    if isinstance(instr.argval, int):
        return instr.argval
    return None


UNARY_OPS = {
    "UNARY_POSITIVE": ast.UAdd,
    "UNARY_NEGATIVE": ast.USub,
    "UNARY_NOT": ast.Not,
    "UNARY_INVERT": ast.Invert,
}

BINARY_OPS = {
    "BINARY_ADD": ast.Add,
    "BINARY_SUBTRACT": ast.Sub,
    "BINARY_MULTIPLY": ast.Mult,
    "BINARY_MATRIX_MULTIPLY": ast.MatMult,
    "BINARY_TRUE_DIVIDE": ast.Div,
    "BINARY_FLOOR_DIVIDE": ast.FloorDiv,
    "BINARY_MODULO": ast.Mod,
    "BINARY_POWER": ast.Pow,
    "BINARY_LSHIFT": ast.LShift,
    "BINARY_RSHIFT": ast.RShift,
    "BINARY_AND": ast.BitAnd,
    "BINARY_OR": ast.BitOr,
    "BINARY_XOR": ast.BitXor,
}

INPLACE_OPS = {
    "INPLACE_ADD": ast.Add,
    "INPLACE_SUBTRACT": ast.Sub,
    "INPLACE_MULTIPLY": ast.Mult,
    "INPLACE_MATRIX_MULTIPLY": ast.MatMult,
    "INPLACE_TRUE_DIVIDE": ast.Div,
    "INPLACE_FLOOR_DIVIDE": ast.FloorDiv,
    "INPLACE_MODULO": ast.Mod,
    "INPLACE_POWER": ast.Pow,
    "INPLACE_LSHIFT": ast.LShift,
    "INPLACE_RSHIFT": ast.RShift,
    "INPLACE_AND": ast.BitAnd,
    "INPLACE_OR": ast.BitOr,
    "INPLACE_XOR": ast.BitXor,
}

COMPARE_OPS = {
    "<": ast.Lt,
    "<=": ast.LtE,
    "==": ast.Eq,
    "!=": ast.NotEq,
    ">": ast.Gt,
    ">=": ast.GtE,
    "in": ast.In,
    "not in": ast.NotIn,
    "is": ast.Is,
    "is not": ast.IsNot,
    "exception match": ast.Eq,
    "BAD": ast.Eq,
}


@dataclass
class BlockInfo:
    start: int
    end: int
    kind: str = "basic"
    body: Optional[List[ast.stmt]] = None


class ASTNode:
    @staticmethod
    def make_Name(id: str, ctx=ast.Load()) -> ast.Name:
        return ast.Name(id=id, ctx=ctx)

    @staticmethod
    def make_Constant(value: Any) -> ast.Constant:
        return ast.Constant(value=value)

    @staticmethod
    def make_Expr(value: ast.expr) -> ast.Expr:
        return ast.Expr(value=value)

    @staticmethod
    def make_Assign(targets, value) -> ast.Assign:
        return ast.Assign(targets=targets, value=value)

    @staticmethod
    def make_AugAssign(target, op, value) -> ast.AugAssign:
        return ast.AugAssign(target=target, op=op, value=value)

    @staticmethod
    def make_Return(value=None) -> ast.Return:
        return ast.Return(value=value)

    @staticmethod
    def make_Call(func, args, keywords=None) -> ast.Call:
        return ast.Call(func=func, args=args, keywords=keywords or [])


class _FuncDefHolder(ast.expr):
    _fields = ()
    _attributes = ("lineno", "col_offset", "end_lineno", "end_col_offset")

    def __init__(
        self,
        func_def: ast.FunctionDef,
        annotations: Optional[ast.expr] = None,
        defaults: Optional[ast.expr] = None,
        kw_defaults: Optional[ast.expr] = None,
        closure: Optional[ast.expr] = None,
    ):
        super().__init__()
        self.func_def = func_def
        self.annotations = annotations
        self.defaults = defaults
        self.kw_defaults = kw_defaults
        self.closure = closure
        self.lineno = 0
        self.col_offset = 0

    def apply_extras(self) -> None:
        """Merge the ``MAKE_FUNCTION`` operands into the emitted ``FunctionDef``."""
        fn = self.func_def
        args = fn.args
        pos_defaults = self._as_sequence(self.defaults)
        if pos_defaults:
            args.defaults = pos_defaults
        if isinstance(self.kw_defaults, ast.Dict) and self.kw_defaults.keys:
            for key, value in zip(self.kw_defaults.keys, self.kw_defaults.values):
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                    continue
                for i, slot in enumerate(args.kwonlyargs):
                    if slot.arg == key.value:
                        args.kw_defaults[i] = value
                        break
        if not isinstance(self.annotations, ast.Dict):
            return
        slots: List[ast.arg] = list(args.posonlyargs) + list(args.args)
        slots += list(args.kwonlyargs)
        if args.vararg is not None:
            slots.append(args.vararg)
        if args.kwarg is not None:
            slots.append(args.kwarg)
        for key, value in zip(self.annotations.keys, self.annotations.values):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if key.value == "return":
                fn.returns = value
                continue
            for slot in slots:
                if slot.arg == key.value:
                    slot.annotation = value
                    break

    @staticmethod
    def _as_sequence(node: Optional[ast.expr]) -> Optional[List[ast.expr]]:
        """Normalise a ``MAKE_FUNCTION`` tuple operand into a list of expressions.

        CPython folds a tuple of constants into a single ``LOAD_CONST``, so a
        default like ``b: int = 2`` arrives as a constant ``(2,)`` rather than a
        ``BUILD_TUPLE`` node.
        """
        if isinstance(node, ast.Tuple):
            return list(node.elts)
        if isinstance(node, ast.Constant) and isinstance(node.value, tuple):
            return [ast.Constant(value=v) for v in node.value]
        return None


class _ClassCodeHolder(ast.expr):
    _fields = ()
    _attributes = ("lineno", "col_offset", "end_lineno", "end_col_offset")

    def __init__(self, code_obj):
        super().__init__()
        self.code_obj = code_obj
        self.lineno = 0
        self.col_offset = 0


class _MethodRef(ast.expr):
    """Marker pushed by LOAD_METHOD: an unbound method name awaiting CALL_METHOD."""

    _fields = ()
    _attributes = ("lineno", "col_offset", "end_lineno", "end_col_offset")

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.lineno = 0
        self.col_offset = 0


class _ClosureRef(ast.expr):
    """Marker pushed by LOAD_CLOSURE: a free-var name awaiting BUILD_TUPLE."""

    _fields = ()
    _attributes = ("lineno", "col_offset", "end_lineno", "end_col_offset")

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.lineno = 0
        self.col_offset = 0


#: Sentinel meaning "this block does not return a value", so that a legitimate
#: ``None`` constant can still be told apart from the absence of a return.
_NO_RETURN = object()


def _is_bare_return(node: ast.stmt) -> bool:
    """True for ``return`` / ``return None``, which the compiler also emits bare.

    A function whose last statement falls off the end compiles to an implicit
    ``LOAD_CONST None; RETURN_VALUE``, which is not source level at all.
    """
    if not isinstance(node, ast.Return):
        return False
    value = node.value
    return value is None or (
        isinstance(value, ast.Constant) and value.value is None
    )


class _CompMaker(ast.expr):
    """Marker pushed by MAKE_FUNCTION for a comprehension code object.

    A comprehension is compiled as a nested code object taking the iterable as
    its single argument; the marker keeps the code object around until the
    enclosing ``CALL_FUNCTION`` supplies that iterable.
    """

    _fields = ()
    _attributes = ("lineno", "col_offset", "end_lineno", "end_col_offset")

    def __init__(self, code_obj):
        super().__init__()
        self.code_obj = code_obj
        self.lineno = 0
        self.col_offset = 0


def _merge_dicts(target, other):
    """Combine two dict expressions produced by ``DICT_MERGE``/``DICT_UPDATE``.

    ``BUILD_MAP 0`` emits an empty dict that only exists as the merge target, and
    the compiler flattens ``{**a, 'b': 1}`` into two successive updates.  An
    empty side therefore disappears, and a non-literal side becomes a ``**``
    entry (``key=None``) so the round trip keeps the spread.
    """

    def as_items(node):
        if isinstance(node, ast.Dict):
            return list(zip(node.keys, node.values))
        return None

    left = as_items(target)
    right = as_items(other)
    if left == []:
        return other
    if right == []:
        return target
    if left is None:
        left = [(None, target)]
    if right is None:
        right = [(None, other)]
    items = left + right
    return ast.Dict(keys=[k for k, _ in items], values=[v for _, v in items])


class Decompiler:
    # Opcodes that can appear between the head of a ``while`` condition and the
    # ``POP_JUMP_IF_*`` that consumes it.  Anything outside this set means the
    # backward jump found at that offset belongs to a ``while True:`` body
    # instead of a conditional loop.
    _COND_EXPR_OPS = {
        "LOAD_CONST", "LOAD_NAME", "LOAD_FAST", "LOAD_GLOBAL", "LOAD_DEREF",
        "LOAD_CLOSURE", "LOAD_CLASSDEREF", "LOAD_METHOD", "LOAD_ATTR",
        "DUP_TOP", "DUP_TOP_TWO", "ROT_TWO", "ROT_THREE", "ROT_FOUR", "ROT_N",
        "BINARY_ADD", "BINARY_SUBTRACT", "BINARY_MULTIPLY", "BINARY_FLOOR_DIVIDE",
        "BINARY_TRUE_DIVIDE", "BINARY_MODULO", "BINARY_POWER", "BINARY_AND",
        "BINARY_OR", "BINARY_XOR", "BINARY_LSHIFT", "BINARY_RSHIFT",
        "INPLACE_ADD", "INPLACE_SUBTRACT", "INPLACE_MULTIPLY",
        "INPLACE_FLOOR_DIVIDE", "INPLACE_TRUE_DIVIDE", "INPLACE_MODULO",
        "INPLACE_POWER", "INPLACE_AND", "INPLACE_OR", "INPLACE_XOR",
        "INPLACE_LSHIFT", "INPLACE_RSHIFT",
        "UNARY_NEGATIVE", "UNARY_POSITIVE", "UNARY_NOT", "UNARY_INVERT",
        "COMPARE_OP", "IS_OP", "CONTAINS_OP", "BINARY_SUBSCR",
        "CALL_FUNCTION", "CALL_FUNCTION_KW", "CALL_FUNCTION_EX", "CALL_METHOD",
        "BUILD_TUPLE", "BUILD_LIST", "BUILD_SET", "BUILD_STRING",
        "BUILD_CONST_KEY_MAP", "BUILD_MAP", "BUILD_SLICE",
        "FORMAT_VALUE", "LIST_EXTEND", "SET_UPDATE", "DICT_UPDATE",
        "DICT_MERGE", "KW_NAMES",
    }

    def __init__(self):
        self.dis = Disassembler()
        # Closure-variable tracking (LOAD_CLOSURE -> BUILD_TUPLE -> MAKE_FUNCTION).
        # These are the two attributes a nested code object legitimately
        # *inherits* from the scope that defines it, so they are part of the
        # instance rather than of the per-code-object state.
        self._pending_closure_names: List[str] = []
        self._current_closure: Optional[List[str]] = None
        self._closure_names: Optional[set] = None
        self._reset_reconstruction_state()

    #: Reconstruction state that belongs to exactly one code object.  Anything
    #: listed here is reset when a nested code object is decompiled, because
    #: the values are indices and offsets into one particular instruction
    #: stream (``_handled_ranges``) or per-scope bookkeeping (``_imported_modules``).
    _SCOPED_STATE = (
        ("_import_ctx_module", lambda: None),
        ("_import_ctx_level", lambda: 0),
        ("_import_ctx_names", list),
        ("_pending_from_names", list),
        ("_exc_stack", list),
        ("_imported_modules", set),
        ("_handled_ranges", list),
        ("_loop_stack", list),
        ("_loop_heads", set),
        ("_tails_at_merge", dict),
    )

    def _reset_reconstruction_state(self) -> None:
        for name, factory in self._SCOPED_STATE:
            setattr(self, name, factory())

    @contextmanager
    def _isolated_state(self):
        """Decompile a nested code object without touching the caller's state.

        Reusing one :class:`Decompiler` across code objects used to let the
        inner one inherit the outer's bookkeeping: ``_imported_modules`` made
        the second ``import`` in a function disappear, and ``_handled_ranges``
        stores instruction indices that restart at 0 for every code object, so
        the inner body inherited the outer loop's already-consumed ranges.
        """
        saved = {
            name: getattr(self, name)
            for name, _ in self._SCOPED_STATE
            if hasattr(self, name)
        }
        try:
            self._reset_reconstruction_state()
            yield self
        finally:
            self._reset_reconstruction_state()
            for name, value in saved.items():
                setattr(self, name, value)

    def _emit_statements_safe(self, code, instructions: List[Instruction], **kwargs) -> List[ast.stmt]:
        """Backwards-compatible alias for _emit_statements."""
        return self._emit_statements(code, instructions, **kwargs)

    def _indent(self, level: int) -> str:
        return "    " * level

    def decompile(self, code) -> str:
        if hasattr(code, "co_filename") and code.co_name == "<module>":
            return self._decompile_module(code)
        else:
            return self._decompile_code_object(code, indent_level=0)

    def _decompile_module(self, code) -> str:
        return self._decompile_code_object(code, indent_level=0, is_module=True)

    def _restore_docstring(self, stmts: List[ast.stmt]) -> List[ast.stmt]:
        """Turn a leading ``__doc__ = '...'`` back into a real docstring.

        CPython compiles a docstring to a ``STORE_NAME __doc__``, so it comes
        back as a plain assignment.  A bare assignment would also be invalid in a
        module that starts with ``from __future__ import ...``.
        """
        if not stmts:
            return stmts
        first = stmts[0]
        if not (
            isinstance(first, ast.Assign)
            and len(first.targets) == 1
            and isinstance(first.targets[0], ast.Name)
            and first.targets[0].id == "__doc__"
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            return stmts
        return [ast.Expr(value=first.value)] + list(stmts[1:])

    @staticmethod
    def _restore_scope_declarations(code, instrs, stmts: List[ast.stmt]) -> List[ast.stmt]:
        """Recover the ``global``/``nonlocal`` declarations a function body drops.

        Neither statement emits bytecode of its own: the compiler only marks the
        affected accesses as ``*_GLOBAL``/``*_DEREF`` and records the binding in
        the code object, so the declaration has to be rebuilt from the stores.
        A free variable that is only *read* needs no declaration, and a
        ``STORE_DEREF`` on a name this function binds itself is just a cell
        variable shared with a nested scope -- neither is declared.
        """
        heads: List[ast.stmt] = []
        globals_: List[str] = []
        for ins in instrs:
            name = ins.argval
            if ins.opname in ("STORE_DEREF", "DELETE_DEREF"):
                # ``__class__`` is injected by the compiler for a zero-argument
                # ``super()``; the source never declares it.
                if name in code.co_freevars and name != "__class__":
                    heads.append(ast.Nonlocal(names=[name]))
            elif ins.opname in ("STORE_GLOBAL", "DELETE_GLOBAL") and name not in globals_:
                globals_.append(name)
        heads.extend(ast.Global(names=[name]) for name in globals_)
        if not heads:
            return stmts
        at = 1 if stmts and isinstance(stmts[0], ast.Expr) else 0
        return stmts[:at] + heads + stmts[at:]

    @staticmethod
    def _prepend_function_docstring(func_code, instrs, stmts: List[ast.stmt]) -> List[ast.stmt]:
        """Recover a function docstring, which emits no bytecode at all.

        Unlike a module or class body, a function docstring leaves no trace in
        the instruction stream -- CPython only parks it in ``co_consts[0]``.  A
        class body shares that slot with ``__qualname__``, so it is excluded by
        its ``__module__`` prologue; its own docstring arrives as a ``__doc__``
        store and is handled by :meth:`_restore_docstring`.
        """
        consts = getattr(func_code, "co_consts", ())
        if not consts or not isinstance(consts[0], str):
            return stmts
        # 3.14 dropped the ``None`` placeholder that used to keep a real
        # constant out of ``co_consts[0]``, so the slot alone no longer means
        # "docstring": ``def f(a): return f'{a}>x'`` parks ``'>'`` there.  A
        # docstring is the one constant that is never loaded, so a load of the
        # same value rules it out.
        if any(
            getattr(ins, "opname", "").startswith("LOAD")
            and getattr(ins, "argval", None) == consts[0]
            for ins in instrs
        ):
            return stmts
        if (
            len(instrs) >= 2
            and instrs[0].opname == "LOAD_NAME"
            and instrs[0].argval == "__name__"
            and instrs[1].opname == "STORE_NAME"
        ):
            return stmts
        return [ast.Expr(value=ast.Constant(value=consts[0]))] + list(stmts)

    def _merge_annassigns(self, stmts: List[ast.stmt]) -> List[ast.stmt]:
        """Rebuild ``x: T = v`` from the ``__annotations__['x'] = T`` store.

        An annotated assignment compiles to a plain store followed by a
        subscript store into the ``__annotations__`` dict created by
        ``SETUP_ANNOTATIONS``.  Merging the two back restores the source form
        and re-triggers ``SETUP_ANNOTATIONS`` on recompile.
        """
        out: List[ast.stmt] = []
        i = 0
        while i < len(stmts):
            cur = stmts[i]
            nxt = stmts[i + 1] if i + 1 < len(stmts) else None
            if (
                isinstance(nxt, ast.Assign)
                and len(nxt.targets) == 1
                and isinstance(nxt.targets[0], ast.Subscript)
                and self._is_annotations_target(nxt.targets[0])
                and isinstance(nxt.targets[0].slice, ast.Constant)
                and isinstance(nxt.targets[0].slice.value, str)
            ):
                name = nxt.targets[0].slice.value
                if isinstance(cur, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == name for t in cur.targets
                ):
                    out.append(
                        ast.AnnAssign(
                            target=ASTNode.make_Name(name, ast.Store()),
                            annotation=nxt.value,
                            value=cur.value,
                            simple=1,
                        )
                    )
                    i += 2
                    continue
                out.append(
                    ast.AnnAssign(
                        target=ASTNode.make_Name(name, ast.Store()),
                        annotation=nxt.value,
                        value=None,
                        simple=1,
                    )
                )
                i += 2
                continue
            out.append(cur)
            i += 1
        return out

    @staticmethod
    def _is_annotations_target(node: ast.Subscript) -> bool:
        return (
            isinstance(node.value, ast.Name) and node.value.id == "__annotations__"
        )

    def _needs_setup_annotations(self, code) -> bool:
        """True when the module opens with ``SETUP_ANNOTATIONS``.

        The compiler emits it only when a *variable* annotation exists, so the
        re-emitted source needs the same trigger to keep the instruction stream
        identical.  A bare ``pass`` reproduces it without a real annotation.
        """
        instrs = self.dis.disassemble(code)
        return bool(instrs) and instrs[0].opname == "SETUP_ANNOTATIONS"

    def _unstring_annotations(self, stmts: List[ast.stmt]) -> List[ast.stmt]:
        """Restore annotations stringified by ``from __future__ import annotations``.

        With that future import every annotation is compiled as the *source text*
        of the expression, so ``def f(x: int)`` stores the constant ``'int'``.
        Re-parsing those constants recovers the original expression and avoids
        emitting a doubly-quoted ``'int'``.
        """
        has_future = any(
            isinstance(s, ast.ImportFrom)
            and s.module == "__future__"
            and any(a.name == "annotations" for a in s.names)
            for s in stmts
        )
        if not has_future:
            return stmts

        def convert(node: Optional[ast.expr]) -> Optional[ast.expr]:
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                return node
            try:
                return ast.parse(node.value, mode="eval").body
            except SyntaxError:
                return node

        for node in ast.walk(ast.Module(body=stmts, type_ignores=[])):
            if isinstance(node, ast.arg):
                node.annotation = convert(node.annotation)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                node.returns = convert(node.returns)
            elif isinstance(node, ast.AnnAssign):
                node.annotation = convert(node.annotation)
        return stmts

    def _drop_dead_tail(self, stmts: List[ast.stmt]) -> List[ast.stmt]:
        """Remove the unreachable exception-handler tail of a code object.

        The block form of every ``with`` and ``try`` ends with a handler the
        compiler generates: re-raise the in-flight exception and return ``None``
        for the paths that swallowed it.  Those instructions are only reachable
        through the handler, which no source-level ``raise`` here can enter, so
        a ``raise`` that trails every real statement is dead code.

        A bare ``return`` that trails an already-terminating statement is dead
        for the same reason: a function whose last real statement is a chained
        comparison (``return a < b < c``) jumps to the compiler's implicit
        ``return None`` epilogue, which is otherwise unreachable.
        """
        if not stmts:
            return stmts
        # Strip a bare ``return`` that no path can reach because the statement
        # before it already returns/raises/breaks/continues.
        end = len(stmts)
        while (
            end > 1
            and isinstance(stmts[end - 1], ast.Return)
            and stmts[end - 1].value is None
            and isinstance(
                stmts[end - 2],
                (ast.Return, ast.Raise, ast.Break, ast.Continue),
            )
        ):
            end -= 1
        if end != len(stmts):
            stmts = stmts[:end]
        if not stmts or not isinstance(stmts[-1], ast.Raise):
            return stmts
        if stmts[-1].exc is not None or stmts[-1].cause is not None:
            return stmts
        end = len(stmts) - 1
        while end > 0 and isinstance(stmts[end - 1], (ast.Raise, ast.Pass)):
            end -= 1
        if end == 0:
            return stmts
        return stmts[:end]

    @staticmethod
    def _is_bare_finally(instructions: List[Instruction], handler_start_idx: int) -> bool:
        """True when *handler_start_idx* begins a ``try``/``finally`` handler.

        A pure ``finally`` handler starts with an inlined copy of the clause
        (arbitrary statements) and only re-raises *after* that copy.  An
        ``except`` handler on the other hand starts with ``DUP_TOP`` (testing
        the exception type) or bare triple-``POP_TOP`` (catch-all).  A lone
        ``RERAISE`` right at the start is also a finally handler: it means the
        clause was empty so the compiler emitted no copy at all.
        """
        if handler_start_idx >= len(instructions):
            return False
        op = instructions[handler_start_idx].opname
        if op == "RERAISE":
            return True
        if op in ("DUP_TOP", "POP_TOP"):
            return False
        # Inlined copy of the finally clause: any statement-level code, with a
        # trailing RERAISE once the copy has been emitted verbatim.
        for j in range(handler_start_idx, len(instructions)):
            name = instructions[j].opname
            if name == "RERAISE":
                return True
            if name in ("DUP_TOP", "SETUP_FINALLY", "SETUP_EXCEPT",
                        "SETUP_WITH", "SETUP_LOOP", "FOR_ITER"):
                return False
        return False

    def _parse_exception_prologue(
        self,
        instructions: List[Instruction],
        idx: int,
        raw_end: int,
    ) -> Optional[Tuple[Optional[ast.expr], Optional[str], int, int,
                       Optional[int], Optional[int]]]:
        """Parse one ``except`` handler's type-test / binding prefix.

        Returns ``None`` when the instructions starting at *idx* do not look
        like an except handler prefix (i.e. the enclosing SETUP_FINALLY was a
        pure ``finally`` rather than an ``except`` chain).

        Otherwise returns:
        ``(exc_type, exc_name, match_target, prefix_end, as_setup_target,
          as_setup_idx)`` where:

        * *exc_type* is the exception type expression (a Name or Tuple of
          Names), or ``None`` for bare ``except:``.
        * *exc_name* is the ``as e`` binding name, or ``None``.
        * *match_target* is where ``JUMP_IF_NOT_EXC_MATCH`` points: the start
          of the *next* handler in the chain or the final fallthrough
          ``RERAISE``.
        * *prefix_end* is the first index of the user-visible handler body.
        * *as_setup_target* / *as_setup_idx* describe the implicit ``SETUP_FINALLY``
          the compiler inserts for ``as e`` cleanup; both are ``None`` without
          the binding.
        """
        if idx >= raw_end:
            return None
        first = instructions[idx].opname
        if first == "POP_TOP":
            # Bare ``except:`` triple pop, no type test.
            j = idx
            for _ in range(3):
                if j >= raw_end or instructions[j].opname != "POP_TOP":
                    return None
                j += 1
            return None, None, None, j, None, None
        if first != "DUP_TOP":
            return None
        # Collect the type expression: a single Name or a Tuple built from
        # consecutive names via BUILD_TUPLE.
        j = idx + 1
        names: List[ast.Name] = []
        tuple_arity: Optional[int] = None
        match_op_idx: Optional[int] = None
        match_target: Optional[int] = None
        while j < raw_end:
            op = instructions[j]
            if op.opname in ("LOAD_NAME", "LOAD_GLOBAL", "LOAD_FAST",
                             "LOAD_DEREF"):
                names.append(ASTNode.make_Name(str(op.argval), ast.Load()))
                j += 1
                continue
            if op.opname == "BUILD_TUPLE":
                tuple_arity = int(op.arg or 0)
                j += 1
                continue
            if op.opname in ("JUMP_IF_NOT_EXC_MATCH", "CHECK_EXC_MATCH"):
                match_op_idx = j
                match_target = self._jump_target(op)
                j += 1
                break
            return None
        if match_op_idx is None or match_target is None or not names:
            return None
        type_ast: Optional[ast.expr]
        if tuple_arity is None:
            type_ast = names[0]
        else:
            type_ast = ast.Tuple(elts=names[-tuple_arity:], ctx=ast.Load())
        # Drop the exception triple: three POP_TOP (or POP_TOP + STORE_FAST +
        # POP_TOP for ``as e``).
        exc_name: Optional[str] = None
        as_setup_idx: Optional[int] = None
        as_setup_target: Optional[int] = None
        if j < raw_end and instructions[j].opname == "POP_TOP":
            j += 1
            if j < raw_end and instructions[j].opname == "STORE_FAST":
                exc_name = str(instructions[j].argval)
                j += 1
                if j < raw_end and instructions[j].opname == "POP_TOP":
                    j += 1
                if j < raw_end and instructions[j].opname \
                        in ("SETUP_FINALLY", "SETUP_EXCEPT"):
                    as_setup_idx = j
                    as_setup_target = self._jump_target(instructions[j])
                    j += 1
            else:
                # Typed without ``as e``: two remaining POP_TOP.
                for _ in range(2):
                    if j < raw_end and instructions[j].opname == "POP_TOP":
                        j += 1
        return type_ast, exc_name, match_target, j, as_setup_target, as_setup_idx

    def _as_tail_range(
        self, instructions: List[Instruction], inner: int, inner_handler: int
    ) -> Tuple[int, int]:
        """Source-level range of an ``except X as e`` clause's exit sequence.

        The region between the body's ``POP_BLOCK`` and the implicit finally's
        handler opens with the compiler's own cleanup -- ``POP_BLOCK``,
        ``POP_EXCEPT``, ``e = None; STORE e; DELETE e`` -- then a second copy of
        the cleanup, and only then whatever the programmer wrote: the value of a
        ``return`` and the jump that leaves the clause.  Both cleanup copies
        have to come off, and the value must survive: taking only the body lost
        every ``return`` written inside an ``as`` clause.
        """

        def is_cleanup(i: int) -> bool:
            return (
                i + 2 < len(instructions)
                and instructions[i].opname == "LOAD_CONST"
                and instructions[i].argval is None
                and instructions[i + 1].opname in self._STORE_OPS
                and instructions[i + 2].opname == "DELETE_FAST"
                and instructions[i + 1].argval == instructions[i + 2].argval
            )

        start = inner
        while start < inner_handler:
            if instructions[start].opname in ("POP_BLOCK", "POP_EXCEPT", "NOP"):
                start += 1
            elif is_cleanup(start):
                start += 3
            else:
                break
        end = inner_handler
        while end > start and instructions[end - 1].opname in (
            "POP_BLOCK", "POP_EXCEPT", "NOP", "RERAISE"
        ):
            end -= 1
        if end - 3 >= start and is_cleanup(end - 3):
            end -= 3
        return start, end

    def _parse_handler_body(
        self,
        code,
        instructions: List[Instruction],
        body_start: int,
        as_setup_target: Optional[int],
        as_setup_idx: Optional[int],
        fallback_reraise_idx: int,
    ) -> Tuple[List[ast.stmt], int]:
        """Emit one except handler's body.

        Returns ``(body_stmts, post_handler_idx)`` where *post_handler_idx* is
        the index right after the last instruction belonging to this handler
        (i.e. where the outer chain should resume scanning).
        """
        if as_setup_idx is not None and as_setup_target is not None:
            # ``except X as e:`` wraps the user body in an implicit SETUP_FINALLY
            # so that ``e`` is always cleared.  The body runs from the
            # SETUP_FINALLY's *next* instruction to its matching POP_BLOCK;
            # anything between POP_BLOCK and the implicit finally's handler
            # (a trailing RETURN_VALUE) was left on the out_stack by the body.
            inner = self._find_pop_block(instructions, as_setup_idx,
                                         as_setup_target)
            inner_handler = self._find_target_idx(instructions, as_setup_target)
            if inner > inner_handler:
                inner = inner_handler
            body_stack: List[ast.expr] = []
            body = self._emit_statements(
                code, instructions, is_module=False,
                start=as_setup_idx + 1, end=inner, out_stack=body_stack,
            )
            trailing = any(
                instructions[k].opname == "RETURN_VALUE"
                for k in range(inner + 1, min(inner_handler + 1, len(instructions)))
            )
            tail_stmts: List[ast.stmt] = []
            if trailing and not body_stack:
                # A clause that leaves via ``return``/``break``/``continue``
                # carries the value and the jump *after* the body's POP_BLOCK,
                # behind the compiler's own ``e = None; del e`` cleanup.  That
                # region used to be skipped wholesale, which silently dropped a
                # ``return`` written inside an ``as`` clause whenever the body
                # itself left nothing behind -- emit what the programmer wrote.
                tail_start, tail_end = self._as_tail_range(
                    instructions, inner, inner_handler
                )
                if tail_end > tail_start and instructions[tail_end - 1].opname in (
                    "RETURN_VALUE", "RETURN_CONST"
                ):
                    tail_stmts = self._emit_statements(
                        code, instructions, is_module=False,
                        start=tail_start, end=tail_end, out_stack=[],
                    )
            if tail_stmts:
                body.extend(tail_stmts)
            elif trailing and body_stack:
                body.append(ast.Return(value=body_stack[-1]))
            if not body:
                body = [ast.Pass()]
            post = max(inner_handler + 1, as_setup_idx + 1)
            # Advance to the final SETUP_FINALLY RERAISE or skip; the jump to
            # the chain merge point sits right before the handler.
            for k in range(inner, min(inner_handler + 2, len(instructions))):
                if instructions[k].opname in ("JUMP_FORWARD", "JUMP_ABSOLUTE"):
                    post = max(post, k + 1)
                    break
            return body, post
        # Plain handler: body runs from body_start until just before POP_EXCEPT.
        raw_end = fallback_reraise_idx if fallback_reraise_idx > body_start \
            else len(instructions)
        j = body_start
        merge_target: Optional[int] = None
        has_return_tail = False
        pop_except_seen = False
        while j < raw_end:
            op = instructions[j].opname
            if op == "POP_EXCEPT":
                j += 1
                pop_except_seen = True
                if j < len(instructions) and instructions[j].opname \
                        in ("JUMP_FORWARD", "JUMP_ABSOLUTE"):
                    merge_target = self._jump_target(instructions[j])
                    j += 1
                    break
                continue
            if op == "RETURN_VALUE":
                has_return_tail = True
                j += 1
                break
            if op in ("RAISE_VARARGS",):
                j += 1
                break
            if op == "RERAISE":
                break
            if op == "POP_TOP" and not pop_except_seen:
                if j + 2 < raw_end \
                        and instructions[j + 1].opname == "POP_TOP" \
                        and instructions[j + 2].opname == "POP_TOP":
                    break
            j += 1
        body_end = j if j < raw_end else raw_end
        # For RETURN_VALUE tail, emit_statements will include the value in its
        # own out_stack; for POP_EXCEPT + jump, we just emit up to j.
        body_stack: List[ast.expr] = []
        body = self._emit_statements(
            code, instructions, is_module=False, start=body_start, end=body_end,
            out_stack=body_stack,
        )
        if has_return_tail and body_stack:
            body.append(ast.Return(value=body_stack.pop()))
        if not body:
            body = [ast.Pass()]
        post = self._find_target_idx(instructions, merge_target) \
            if merge_target is not None else j
        return body, max(post, j)

    @staticmethod
    def _find_stmt_end_after(instructions: List[Instruction], start: int,
                             raw_end: int) -> int:
        """Best-effort: one past the next terminator-style op after *start*."""
        end_ops = {"POP_TOP", "STORE_FAST", "STORE_NAME", "STORE_DEREF",
                   "STORE_GLOBAL", "POP_EXCEPT", "RETURN_VALUE",
                   "JUMP_FORWARD", "JUMP_ABSOLUTE", "DELETE_FAST",
                   "DELETE_NAME", "DELETE_GLOBAL", "DELETE_DEREF",
                   "POP_BLOCK", "RAISE_VARARGS", "STORE_SUBSCR",
                   "STORE_ATTR", "IMPORT_STAR", "IMPORT_NAME",
                   "CALL_FUNCTION", "CALL_METHOD", "CALL_FUNCTION_KW",
                   "CALL_METHOD_KW", "SETUP_FINALLY", "SETUP_EXCEPT",
                   "FORMAT_VALUE", "BUILD_STRING", "LIST_APPEND",
                   "SET_ADD", "MAP_ADD", "DICT_MERGE", "DICT_UPDATE",
                   "LIST_EXTEND", "SET_UPDATE"}
        for j in range(start, raw_end):
            if instructions[j].opname in end_ops:
                # For calls follow through to the POP that consumes the value.
                k = j + 1
                while k < raw_end and instructions[k].opname == "POP_TOP":
                    k += 1
                return k
        return start + 1

    def _parse_except_handlers(
        self,
        code,
        instructions: List[Instruction],
        handler_start_idx: int,
        try_end_idx: Optional[int] = None,
    ) -> Optional[Tuple[List[ast.ExceptHandler], List[ast.stmt], int]]:
        """Parse the full handler chain starting at *handler_start_idx*.

        Returns ``(handlers, orelse, post_idx)`` or ``None`` when the position
        does not begin an except-handler chain (e.g. it is a pure finally
        handler).  *post_idx* is the instruction just past every handler
        (including the final fallthrough ``RERAISE``).  *try_end_idx* is the
        ``POP_BLOCK`` that closes the body, used to find the ``else`` clause.
        """
        if handler_start_idx >= len(instructions):
            return None
        raw_end = len(instructions)
        prologue = self._parse_exception_prologue(instructions,
                                                  handler_start_idx, raw_end)
        if prologue is None:
            return None
        handlers: List[ast.ExceptHandler] = []
        scan = handler_start_idx
        # For the last handler in the chain its JUMP_IF_NOT_EXC_MATCH lands on
        # the final bare RERAISE; we keep scanning until that index as the
        # fallthrough "match" for the last entry's else.
        merge_targets: List[int] = []
        while scan < raw_end:
            p = self._parse_exception_prologue(instructions, scan, raw_end)
            if p is None:
                break
            exc_type, exc_name, match_target, body_start, as_target, as_idx = p
            reraise_idx = self._find_target_idx(instructions, match_target) \
                if match_target is not None else raw_end
            body, post = self._parse_handler_body(
                code, instructions, body_start, as_target, as_idx, reraise_idx,
            )
            handlers.append(ast.ExceptHandler(type=exc_type, name=exc_name,
                                              body=body))
            # Every clause that handled the exception merges through a jump to
            # the instruction *after* the ``else`` body, so the smallest of
            # those targets is where the clause has to stop.
            for k in range(scan, min(post, len(instructions))):
                if instructions[k].opname in ("JUMP_FORWARD", "JUMP_ABSOLUTE"):
                    merge_targets.append(self._jump_target(instructions[k]))
            if match_target is None:
                scan = post
                break
            scan = reraise_idx
            # ``except X as e``'s implicit finally handler ends with a RERAISE
            # right *before* the fallback RERAISE; step over any trailing
            # instructions up to and including the final fallthrough RERAISE.
            if scan < len(instructions) \
                    and instructions[scan].opname == "RERAISE":
                scan += 1
                break
        # Skip the final fallthrough RERAISE if one remains.
        if scan < len(instructions) and instructions[scan].opname == "RERAISE":
            scan += 1
        # Locate else clause: the try body jumps over the handler straight to it,
        # so the jump right after the body's ``POP_BLOCK`` is the reliable start.
        # The handler's own merge target is *past* the clause and cannot be used.
        orelse: List[ast.stmt] = []
        body_jump_target: Optional[int] = None
        if try_end_idx is not None and try_end_idx + 1 < len(instructions) \
                and instructions[try_end_idx + 1].opname in ("JUMP_FORWARD", "JUMP_ABSOLUTE"):
            body_jump_target = self._jump_target(instructions[try_end_idx + 1])
        if body_jump_target is not None:
            start = self._find_target_idx(instructions, body_jump_target)
            # An ``else`` clause is only there if the handler merges *after*
            # it: the clause sits between the body and the handler's merge
            # point, so the body's jump lands strictly before that point.  When
            # the two coincide there is no clause; when the handler merges
            # earlier still -- the body's jump leaving an enclosing loop, say --
            # the jump is not skipping a clause at all, and the trailing code
            # it lands on must not be absorbed into one.
            skips_clause = body_jump_target in merge_targets
            if not skips_clause and merge_targets:
                first_merge = min(
                    self._find_target_idx(instructions, t) for t in merge_targets
                )
                skips_clause = first_merge <= start
            if start >= scan and not skips_clause:
                end = raw_end
                for tgt in merge_targets:
                    limit = self._find_target_idx(instructions, tgt)
                    if start < limit < end:
                        end = limit
                for j in range(start, end):
                    op = instructions[j].opname
                    if op in ("RERAISE", "SETUP_FINALLY", "SETUP_EXCEPT"):
                        end = j
                        break
                    if op == "RETURN_VALUE":
                        # A ``return None`` the compiler parked after the clause
                        # is an epilogue, not part of it -- but a ``return`` the
                        # clause actually wrote is part of it, together with the
                        # ``RETURN_VALUE`` that consumes its value.
                        if j > start and instructions[j - 1].opname == "LOAD_CONST" \
                                and instructions[j - 1].argval is None:
                            end = j - 1
                        else:
                            end = j + 1
                        break
                # A function that ends right after the clause has no merge
                # jump to bound it, so the scan above stops at the
                # ``RETURN_VALUE`` of the implicit ``return None``.  Resume at
                # its ``LOAD_CONST`` instead, which is where 3.9's merge jump
                # would have pointed.
                if end < raw_end and instructions[end].opname == "RETURN_VALUE" \
                        and end > start \
                        and instructions[end - 1].opname == "LOAD_CONST" \
                        and instructions[end - 1].argval is None:
                    end -= 1
                if end > start:
                    orelse = self._emit_statements(
                        code, instructions, is_module=False, start=start,
                        end=end, out_stack=[],
                    )
                    if orelse:
                        scan = max(scan, end)
        return handlers, orelse, scan

    #: Opcodes that only unwind a block rather than run source, so they can sit
    #: between the end of a ``try`` body and its handler without being an
    #: ``else`` clause.
    _BLOCK_NOISE = frozenset((
        "POP_BLOCK", "POP_EXCEPT", "POP_TOP", "DUP_TOP", "COPY", "SWAP",
        "WITH_EXCEPT_START", "POP_JUMP_IF_TRUE", "RERAISE", "CLEANUP_THROW",
        "JUMP_FORWARD", "JUMP_ABSOLUTE", "NOP", "PUSH_EXC_INFO",
    ))

    def _recover_else_clause(
        self,
        code,
        instructions: List[Instruction],
        try_end_idx: int,
        handler_start_idx: int,
        post: int,
    ) -> List[ast.stmt]:
        """Recover an ``else`` clause sitting between the body and the handler.

        3.11 keeps the clause inline there instead of jumping over the handler
        to reach it as 3.9 did, so the back-translated stream leaves it in the
        gap.  Only real statements count: the gap also holds the cleanup of any
        ``with`` the body opened, which the handler takes over.
        """
        gap = [k for k in range(try_end_idx + 1, handler_start_idx)
               if instructions[k].opname not in self._BLOCK_NOISE]
        if not gap:
            return []
        end = gap[-1] + 1
        # The ``POP_TOP`` that discards an expression statement's value belongs
        # to the statement it closes, so the run right after the last real
        # instruction is part of the clause.  A ``POP_TOP`` further out belongs
        # to a ``with`` block the body opened, which the handler takes over.
        probe = end
        while probe < handler_start_idx \
                and instructions[probe].opname == "POP_TOP":
            probe += 1
        end = probe
        # A ``return`` epilogue the compiler parked after the clause is not
        # part of it.
        if instructions[end - 1].opname == "RETURN_VALUE":
            end -= 1
            if end > gap[-1] + 1 or (
                    end - 1 >= gap[0]
                    and instructions[end - 1].opname == "LOAD_CONST"):
                end -= 1
            if end <= gap[0]:
                return []
        orelse = self._emit_statements(
            code, instructions, is_module=False, start=gap[0], end=end,
            out_stack=[],
        )
        if not orelse and end < gap[-1] + 1:
            # The gap held nothing but the ``return`` treated as an epilogue
            # above, so the clause *is* that ``return``.  ``else: return x``
            # compiles to the same two instructions as a trailing ``return x``
            # after the whole ``try``, and the two readings are only told apart
            # by what else the gap holds -- when it holds nothing, the ``else``
            # is the only reading that accounts for the instructions at all.
            end = gap[-1] + 1
            orelse = self._emit_statements(
                code, instructions, is_module=False, start=gap[0], end=end,
                out_stack=[],
            )
        if not orelse:
            return []
        self._handled_ranges.append((gap[0], end))
        return orelse

    def _is_return_after_finally(
        self, instructions: List[Instruction], resume: Optional[int]
    ) -> bool:
        """True when the inline finally copy is followed by a ``return``.

        A ``return`` that is the last statement of a ``try``/``finally`` body is
        compiled after the inline finally copy -- ``POP_BLOCK``, the clause, then
        either the value and ``RETURN_VALUE``, or just ``RETURN_VALUE`` when the
        body already left the value on the stack -- so the clause's own end is
        one instruction short of the return.
        """
        if resume is None or resume >= len(instructions):
            return False
        if instructions[resume].opname == "RETURN_VALUE":
            return True
        return (
            resume + 1 < len(instructions)
            and instructions[resume + 1].opname == "RETURN_VALUE"
        )

    def _collect_finally_body(
        self,
        code,
        instructions: List[Instruction],
        try_end_idx: int,
        handler_start_idx: int,
    ):
        """Recover the ``finally`` clause of a ``try``/``finally``.

        With no ``except`` handler the compiler emits the ``finally`` body twice:
        once inline where the protected range ends, and once in the handler
        where it runs before the re-raise.  The inline copy is the source level
        one, so it is the one to read; the handler copy is skipped.

        3.11 runs the clause inline *and* leaves the code that follows the
        ``try`` right behind it, before the handler rather than after it as 3.9
        did.  The handler holds a verbatim copy of the clause, so its length
        says how much of the inline run belongs to the clause.

        Returns the clause and the index the enclosing statement resumes at,
        which is ``None`` when 3.9 closed the inline copy with a forward jump
        over the handler and that jump is the better boundary.
        """
        if handler_start_idx <= try_end_idx or handler_start_idx >= len(instructions):
            return [], None
        start = try_end_idx + 1
        # 3.9 ran the clause inline and then jumped over the handler; the jump
        # is the boundary, and the code after the ``try`` is past the handler.
        if instructions[start].opname in ("JUMP_FORWARD", "JUMP_ABSOLUTE"):
            end = start
            resume = None
        else:
            length = self._finally_clause_length(instructions, handler_start_idx)
            end = min(handler_start_idx, start + length)
            if length or instructions[start].opname != "RETURN_VALUE":
                resume = end
            else:
                # A ``return`` straight after the block pop is the body's own,
                # already folded into the body above; everything the ``try``
                # encloses follows the handler as it did in 3.9.
                resume = None
        if end <= start:
            return [], resume
        body = self._emit_statements(
            code, instructions, is_module=False, start=start, end=end,
            out_stack=[],
        )
        # The handler -- and, when a nested ``finally`` unwinds through it, its
        # prologue -- is not source.  Mark it only *after* the inline copy has
        # been read: the prologue range reaches back over the copy, so marking
        # first hides the very statements this clause is recovered from.
        self._handled_ranges.append((
            self._handler_prologue_start(
                instructions, handler_start_idx, length
            ),
            self._handler_end(instructions, handler_start_idx),
        ))
        # The inline copy is followed by the handler's own re-raise, which is
        # not part of the clause.
        while body and (
            isinstance(body[-1], (ast.Pass, ast.Raise)) or _is_bare_return(body[-1])
        ):
            body.pop()
        return body, resume

    def _finally_clause_length(
        self, instructions: List[Instruction], handler_start_idx: int
    ) -> int:
        """How many instructions the inline copy of a ``finally`` clause has.

        The copy starts after the block-pop the handler prologue opens with and
        ends at the re-raise that follows it, so the handler's own length is
        the clause's length.
        """
        n = len(instructions)
        if instructions[handler_start_idx].opname == "RERAISE":
            return 0
        start = handler_start_idx
        while start < n and instructions[start].opname in self._BLOCK_NOISE:
            start += 1
        end = start
        while end < n and instructions[end].opname != "RERAISE":
            end += 1
        return end - start

    def _handler_prologue_start(
        self,
        instructions: List[Instruction],
        handler_start_idx: int,
        length: int,
    ) -> int:
        """Index where a nested handler's body really begins.

        When a ``finally`` sits inside another ``try``, 3.9 emits the outer
        handler in two halves::

            POP_BLOCK          <- the outer body ends
            <finally body>     <- cleanup before re-raising
            JUMP_FORWARD merge <- cleanup when nothing was raised
            <finally body>     <- what SETUP_FINALLY actually targets
            RERAISE

        Only the second half is the ``SETUP_FINALLY`` target, so starting the
        handler there leaves the first half in the stream and it is emitted a
        second time after the statement it belongs to.  When that shape is
        present the handler has to be considered to start at the ``POP_BLOCK``.
        """
        if not length:
            return handler_start_idx
        jump_idx = handler_start_idx - 1
        pop_idx = jump_idx - length - 1
        if pop_idx < 0:
            return handler_start_idx
        if instructions[jump_idx].opname not in ("JUMP_FORWARD", "JUMP_ABSOLUTE"):
            return handler_start_idx
        if instructions[pop_idx].opname != "POP_BLOCK":
            return handler_start_idx
        return pop_idx

    def _handler_end(
        self, instructions: List[Instruction], handler_start_idx: int
    ) -> int:
        """Index just past the handler of a ``try``/``finally``.

        The handler ends at the re-raise that propagates the exception, or at
        whatever leaves the function when the clause swallows it.
        """
        n = len(instructions)
        for j in range(handler_start_idx, n):
            if instructions[j].opname in ("RERAISE", "RETURN_VALUE"):
                return j + 1
            if instructions[j].opname in ("SETUP_FINALLY", "SETUP_EXCEPT"):
                return j
        return n

    def _decompile_code_object(self, code, indent_level: int, is_module: bool = False) -> str:
        # Every code object gets its own copy of the reconstruction state.
        # ``_handled_ranges`` in particular stores *instruction indices*, which
        # restart at 0 in each code object, and ``_imported_modules`` is a set
        # that has to stay per-scope -- without this, decompiling a nested
        # function on the same instance silently deletes its ``import``
        # statements and inherits the enclosing loop's jump offsets.
        with self._isolated_state():
            instructions = self.dis.disassemble(code)
            if not instructions:
                return self._indent(indent_level) + "pass"
            stmts = self._emit_statements(code, instructions, is_module=is_module)
            stmts = self._drop_dead_tail(stmts)
            stmts = self._restore_docstring(stmts)
            if not is_module:
                stmts = self._restore_scope_declarations(code, instructions, stmts)
            if is_module:
                stmts = self._merge_annassigns(stmts)
                stmts = self._unstring_annotations(stmts)
            if not stmts:
                # An empty result for a code object that has instructions is not
                # a decompilation, it is a failure -- a shape the reader could
                # not fold, most often an exception-group handler on 3.11+.
                # Saying so is far better than handing back a blank file.
                raise DecompilationError(
                    "%s produced no statements from %d instructions"
                    % (getattr(code, "co_name", "<code>"), len(instructions))
                )
            return self._statements_to_source(stmts, indent_level, code, is_module=is_module)

    @contextmanager
    def _isolated_state(self):
        """Run a nested decompilation without leaking state into the caller."""
        saved = {
            name: (list(value) if isinstance(value, list)
                   else set(value) if isinstance(value, set)
                   else dict(value) if isinstance(value, dict)
                   else value)
            for name, value in vars(self).items()
            if name.startswith("_") and not name.startswith("__")
        }
        try:
            yield self
        finally:
            for name in list(vars(self)):
                if name.startswith("_") and name not in saved:
                    delattr(self, name)
            for name, value in saved.items():
                setattr(self, name, value)

    def _emit_statements(
        self,
        code,
        instructions: List[Instruction],
        is_module: bool = False,
        start: int = 0,
        end: Optional[int] = None,
        out_stack: Optional[List[ast.expr]] = None,
    ) -> List[ast.stmt]:
        stack: List[ast.expr] = []
        stmts: List[ast.stmt] = []
        i = start
        n = len(instructions) if end is None else end
        total = len(instructions)
        while i < n:
            # ``while cond:`` -- the head is the condition, guarded by POP_JUMP_IF_*.
            # This must be tried before ``while True`` because the body of a
            # ``while True`` may also contain jumps back to its own head.
            while_cond = self._find_while_cond(instructions, i, n)
            if while_cond is not None:
                cond_jump, back_edge, loop_end = while_cond
                self._emit_while_cond(
                    code, instructions, i, n, cond_jump, back_edge, loop_end, stmts
                )
                i = loop_end
                continue
            # ``while True:`` has no POP_JUMP_IF_* guard -- the only marker is the
            # backward jump at the end of the body that targets the statement head.
            back_edge = self._find_while_true_back_edge(instructions, i, n)
            if back_edge is not None:
                loop_end = self._compute_loop_end(instructions, i, back_edge)
                exit_offset = (
                    instructions[loop_end].offset
                    if loop_end < total
                    else instructions[-1].offset + 2
                )
                body_stmts = self._emit_loop_body(
                    code, instructions, i, back_edge, instructions[i].offset, exit_offset,
                )
                stmts.append(
                    ast.While(test=ast.Constant(value=True), body=body_stmts, orelse=[])
                )
                i = loop_end
                continue
            # Skip instructions that form the body of a try block opened in *this*
            # emission range: they are emitted recursively by the POP_BLOCK handler.
            if self._exc_stack:
                skip = False
                for block in self._exc_stack:
                    if start <= block["instr_start"] < i < block["try_end_idx"]:
                        skip = True
                        break
                if skip:
                    i += 1
                    continue
            # Skip instructions already consumed by an enclosing control-flow construct
            already_handled = False
            for r_start, r_end in self._handled_ranges:
                if r_start <= i < r_end:
                    already_handled = True
                    break
            if already_handled:
                i += 1
                continue
            instr = instructions[i]
            chain_consumed = self._try_emit_chain_cond(
                code, instructions, i, n, stack, stmts
            )
            if chain_consumed:
                i += chain_consumed
                continue
            boolop_consumed = self._try_emit_boolop(
                code, instructions, i, n, stack, stmts
            )
            if boolop_consumed:
                i += boolop_consumed
                continue
            value_chain_consumed = self._try_emit_value_chain(
                code, instructions, i, n, stack
            )
            if value_chain_consumed:
                i += value_chain_consumed
                continue
            value_boolop_consumed = self._try_emit_value_boolop(
                code, instructions, i, n, stack
            )
            if value_boolop_consumed:
                i += value_boolop_consumed
                continue
            ifexp_consumed = self._try_emit_ifexp(
                code, instructions, i, n, stack, stmts, allow_return=True
            )
            if ifexp_consumed:
                i += ifexp_consumed
                continue
            # Implicit `return None` tail of a function body.
            if i + 1 == total - 1 and instr.opname == "LOAD_CONST" and instr.argval is None:
                next_instr = instructions[i + 1] if i + 1 < total else None
                if next_instr and next_instr.opname == "RETURN_VALUE":
                    break
            consumed = self._process_instruction(
                instr, instructions, i, code, stack, stmts,
                is_module=is_module, limit=n,
            )
            # A handler that reports "I consumed nothing" must never be able to
            # report a negative count either: several scanners return
            # ``end_idx - idx``, and a FOR_ITER whose exit target sits at or
            # below its own offset makes that negative, which would walk the
            # index backwards forever.
            i += consumed if consumed and consumed > 0 else 1
        if out_stack is not None:
            out_stack.extend(stack)
        return stmts

    _STORE_OPS = ("STORE_FAST", "STORE_NAME", "STORE_GLOBAL", "STORE_DEREF", "STORE_CLASSDEREF")

    def _parse_store_target(
        self, instructions: List[Instruction], i: int
    ) -> Tuple[Optional[ast.expr], int]:
        """Parse one (possibly nested) assignment target at ``i``.

        Returns ``(target, next_idx)``; ``target`` is ``None`` when the
        instruction at ``i`` does not start a store target.
        """
        if i >= len(instructions):
            return None, i
        cur = instructions[i]
        if cur.opname in self._STORE_OPS:
            return ASTNode.make_Name(str(cur.argval), ast.Store()), i + 1
        if cur.opname == "UNPACK_SEQUENCE":
            count = cur.arg or 0
            elts: List[ast.expr] = []
            j = i + 1
            for _ in range(count):
                elt, j = self._parse_store_target(instructions, j)
                if elt is None:
                    return None, i
                elts.append(elt)
            if count == 1:
                return elts[0], j
            return ast.Tuple(elts=elts, ctx=ast.Store()), j
        if cur.opname in ("LOAD_FAST", "LOAD_NAME", "LOAD_GLOBAL", "LOAD_DEREF"):
            if i + 1 < len(instructions):
                nxt = instructions[i + 1]
                obj = ASTNode.make_Name(str(cur.argval), ast.Load())
                if nxt.opname == "STORE_ATTR":
                    return (
                        ast.Attribute(value=obj, attr=str(nxt.argval), ctx=ast.Store()),
                        i + 2,
                    )
                if nxt.opname == "STORE_SUBSCR":
                    key = instructions[i + 2] if i + 2 < len(instructions) else None
                    return (
                        ast.Subscript(
                            value=obj,
                            slice=(
                                ASTNode.make_Constant(key.argval)
                                if key is not None
                                else None
                            ),
                            ctx=ast.Store(),
                        ),
                        i + 3,
                    )
        return None, i

    def _collect_store_targets(
        self, instructions: List[Instruction], start: int, count: int
    ) -> Tuple[List[ast.expr], int]:
        """Collect up to ``count`` consecutive assignment targets starting at ``start``.

        Returns ``(targets, end_idx)`` where ``end_idx`` is the index just past the
        last consumed store instruction.  Handles plain names, nested
        ``UNPACK_SEQUENCE`` tuples, and the ``LOAD_x; STORE_ATTR`` /
        ``LOAD_x; <key>; STORE_SUBSCR`` target forms.
        """
        targets: List[ast.expr] = []
        end = start
        while end < len(instructions) and len(targets) < count:
            target, nxt = self._parse_store_target(instructions, end)
            if target is None:
                break
            targets.append(target)
            end = nxt
        return targets, end

    def _try_emit_parallel_assign(
        self,
        instructions: List[Instruction],
        idx: int,
        stack: List[ast.expr],
        stmts: List[ast.stmt],
    ) -> int:
        """Collapse a rotation + store run back into a single tuple assignment.

        ``a, b, c = b, c, a`` and ``(d, e), g = (a, b), c`` both compile to a
        series of stack rotations followed by stores.  ``instructions[idx]`` is
        the first such rotation; when the rotations are followed by exactly as
        many store targets as there are rotated stack slots, emit one
        ``Assign`` covering all of them and return the number of instructions
        consumed.  Otherwise return 0 and leave the rotation in place.
        """
        # Replay the rotation(s) that ``idx`` starts, on a copy of the stack.
        sim: List[ast.expr] = list(stack)
        j = idx
        depth = 0
        while j < len(instructions):
            op = instructions[j].opname
            if op == "ROT_TWO":
                if len(sim) < 2:
                    break
                sim[-1], sim[-2] = sim[-2], sim[-1]
                depth = max(depth, 2)
                j += 1
            elif op == "ROT_THREE":
                if len(sim) < 3:
                    break
                sim[-3:] = [sim[-1], sim[-3], sim[-2]]
                depth = max(depth, 3)
                j += 1
            else:
                break
        if depth == 0:
            return 0
        targets, end = self._collect_store_targets(instructions, j, depth)
        if len(targets) != depth or end == j:
            return 0
        # The stores pop in reverse, so the value for ``targets[0]`` is the one
        # the rotation left on top of the stack.
        values = list(reversed(sim[-depth:]))
        stack[:] = sim[:-depth]
        stmts.append(
            ASTNode.make_Assign(
                [ast.Tuple(elts=targets, ctx=ast.Store())],
                ast.Tuple(elts=values, ctx=ast.Load()),
            )
        )
        return end - idx

    _CLASS_ARTIFACT_NAMES = (
        "__module__", "__qualname__", "__classcell__",
        "__firstlineno__", "__static_attributes__",
        "__annotate_func__", "__classdict__", "__classdictcell__",
    )

    def _strip_class_artifacts(self, stmts: List[ast.stmt]) -> List[ast.stmt]:
        """Drop the bookkeeping assignments CPython injects into a class body.

        A class body's code object always starts by binding ``__module__`` and
        ``__qualname__``; neither appears in the original source.
        """
        out: List[ast.stmt] = []
        for s in stmts:
            if (
                isinstance(s, ast.Assign)
                and len(s.targets) == 1
                and isinstance(s.targets[0], ast.Name)
                and s.targets[0].id in self._CLASS_ARTIFACT_NAMES
            ):
                continue
            out.append(s)
        return out

    def _process_instruction(
        self,
        instr: Instruction,
        instructions: List[Instruction],
        idx: int,
        code,
        stack: List[ast.expr],
        stmts: List[ast.stmt],
        is_module: bool = False,
        limit: Optional[int] = None,
    ) -> int:
        opname = instr.opname
        if opname == "LOAD_BUILD_CLASS":
            stack.append(ASTNode.make_Name("__build_class__", ast.Load()))
            return 1
        if opname == "LOAD_CONST":
            stack.append(self._make_constant(instr.argval))
            return 1
        if opname == "LOAD_NAME":
            stack.append(ASTNode.make_Name(str(instr.argval), ast.Load()))
            return 1
        if opname == "LOAD_FAST":
            stack.append(ASTNode.make_Name(str(instr.argval), ast.Load()))
            return 1
        if opname == "LOAD_GLOBAL":
            stack.append(ASTNode.make_Name(str(instr.argval), ast.Load()))
            return 1
        if opname == "LOAD_CLOSURE":
            # Push a marker so BUILD_TUPLE can later pop it and record the
            # closure free-vars.  The marker is not emitted in source output.
            stack.append(_ClosureRef(str(instr.argval)))
            return 1
        if opname in ("LOAD_DEREF", "LOAD_CLASSDEREF"):
            deref_names = set(self._closure_names or ())
            if instr.argval in deref_names:
                stack.append(ASTNode.make_Name(str(instr.argval), ast.Load()))
                return 1
            stack.append(ASTNode.make_Name(str(instr.argval), ast.Load()))
            return 1
        if opname == "LOAD_ATTR":
            if len(stack) < 1:
                stack.append(ASTNode.make_Name(str(instr.argval), ast.Load()))
                return 1
            obj = stack.pop()
            stack.append(ast.Attribute(value=obj, attr=str(instr.argval), ctx=ast.Load()))
            return 1
        if opname == "LOAD_METHOD":
            # 3.9: object stays on the stack, method name pushed as an unbound marker
            stack.append(_MethodRef(str(instr.argval)))
            return 1
        if opname in ("STORE_NAME", "STORE_FAST", "STORE_GLOBAL", "STORE_DEREF", "STORE_CLASSDEREF"):
            if not stack:
                return 1
            val = stack.pop()
            if isinstance(val, ast.Name) and self._pending_from_names \
                    and val.id in (n for n, _ in self._pending_from_names):
                # ``from m import a as b`` binds ``b`` right after ``IMPORT_FROM
                # a``.  The store is part of the import statement, not an
                # assignment, so fold it in as the alias instead of emitting
                # ``b = a`` next to the import that already binds ``b``.
                asname = None if val.id == str(instr.argval) else str(instr.argval)
                self._pending_from_names = [
                    (n, asname if n == val.id else existing) for n, existing in self._pending_from_names
                ]
                return 1
            if isinstance(val, _FuncDefHolder):
                val.apply_extras()
                target = ASTNode.make_Name(str(instr.argval), ast.Store())
                if val.func_def.name == "<lambda>":
                    # ``cb = lambda ...`` is an assignment, not a ``def``.
                    stmts.append(ASTNode.make_Assign([target], self._holder_to_expr(val)))
                    return 1
                val.func_def.name = str(instr.argval)
                stmts.append(val.func_def)
                return 1
            if isinstance(val, ast.Name) and val.id == str(instr.argval):
                return 1
            target = ASTNode.make_Name(str(instr.argval), ast.Store())
            stmts.append(ASTNode.make_Assign([target], val))
            return 1
        if opname == "STORE_ATTR":
            if len(stack) < 2:
                return 1
            obj = stack.pop()
            val = stack.pop()
            target = ast.Attribute(value=obj, attr=str(instr.argval), ctx=ast.Store())
            stmts.append(ASTNode.make_Assign([target], val))
            return 1
        if opname == "STORE_SUBSCR":
            if len(stack) < 3:
                return 1
            # CPython pushes ``value, container, key`` for ``obj[key] = value``.
            key = stack.pop()
            obj = stack.pop()
            val = stack.pop()
            target = ast.Subscript(value=obj, slice=ast.Index(value=key) if sys.version_info < (3, 9) else key, ctx=ast.Store())
            stmts.append(ASTNode.make_Assign([target], val))
            return 1
        if opname == "UNPACK_SEQUENCE":
            if not stack:
                return 1
            seq = stack.pop()
            count = instr.arg or 0
            targets, end = self._collect_store_targets(instructions, idx + 1, count)
            if len(targets) == count and count > 0:
                assign_targets: List[ast.expr] = targets
                if count > 1:
                    assign_targets = [ast.Tuple(elts=targets, ctx=ast.Store())]
                stmts.append(ASTNode.make_Assign(assign_targets, seq))
                return end - idx
            # Fallback: push elements back onto stack (one per target)
            if isinstance(seq, ast.Tuple):
                elts = seq.elts
                if len(elts) >= count:
                    for j in range(count - 1, -1, -1):
                        stack.append(elts[j])
            return 1
        if opname == "UNPACK_EX":
            if not stack:
                return 1
            seq = stack.pop()
            # ``UNPACK_EX`` packs "targets before the star" into the low byte
            # and "targets after the star" into the high byte, then stores
            # ``before + 1 + after`` values in source order.  The slot in the
            # middle binds the list of remaining elements, so the only thing
            # missing is the ``Starred`` wrapper around it.
            limit_idx = len(instructions) if limit is None else limit
            packed = instr.arg or 0
            before, after = packed & 0xFF, packed >> 8
            count = before + after + 1
            j = idx + 1
            targets: List[ast.expr] = []
            for _ in range(count):
                if j >= limit_idx:
                    break
                target, nxt_idx = self._parse_store_target(instructions, j)
                # A slot written as a nested tuple compiles to a whole
                # ``UNPACK_SEQUENCE`` run, which reorders the groups relative to
                # the values on the stack; leave those to the generic path
                # rather than emit an assignment with the terms swapped.
                if nxt_idx != j + 1 or not isinstance(target, ast.Name):
                    targets = []
                    break
                targets.append(target)
                j = nxt_idx
            if len(targets) == count:
                starred = ast.Starred(value=targets[before], ctx=ast.Store())
                elements = targets[:before] + [starred] + targets[before + 1:]
                stmts.append(ASTNode.make_Assign(
                    [ast.Tuple(elts=elements, ctx=ast.Store())], seq
                ))
                return j - idx
            return 1
        if opname == "BINARY_SUBSCR":
            if len(stack) < 2:
                return 1
            key = stack.pop()
            obj = stack.pop()
            # CPython folds ``Literal["a", "b"]`` into a single ``LOAD_CONST`` of
            # the tuple, so no ``BUILD_TUPLE`` is emitted.  Unfold it back into a
            # bare tuple slice, which is the same subscript at runtime.
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, tuple)
                and len(key.value) > 1
            ):
                key = ast.Tuple(
                    elts=[ast.Constant(value=v) for v in key.value], ctx=ast.Load()
                )
            sub = ast.Subscript(value=obj, slice=ast.Index(value=key) if sys.version_info < (3, 9) else key, ctx=ast.Load())
            stack.append(sub)
            return 1
        if opname == "POP_TOP":
            # ``from m import a, b`` ends with POP_TOP once every name is bound.
            # A relative import (``from . import x``) has no module name to key
            # on, so the "did we see an import?" test cannot be the module.
            if self._pending_from_names and self._import_ctx_module is not None:
                stmts.append(
                    ast.ImportFrom(
                        module=self._import_ctx_module or None,
                        names=[
                            ast.alias(name=n, asname=asname)
                            for n, asname in self._pending_from_names
                        ],
                        level=self._import_ctx_level,
                    )
                )
                self._pending_from_names = []
                self._import_ctx_module = None
                self._import_ctx_level = 0
                if stack:
                    stack.pop()
                return 1
            if stack:
                val = stack.pop()
                # ``return`` out of a loop body compiles to ``ROT_TWO`` +
                # ``POP_TOP`` + ``RETURN_VALUE``: the rotation swaps the pending
                # value down, but the iterator it displaces lives on the loop's
                # own stack, so the pop lands on the value itself.  Keep it.
                if self._is_loop_exit_pop(instructions, idx):
                    stack.append(val)
                    return 1
                # Don't emit padding constants (0, None) or stray import Names as statements
                if isinstance(val, ast.Constant) and val.value in (0, None):
                    return 1
                if isinstance(val, ast.Name):
                    return 1
                stmts.append(ASTNode.make_Expr(val))
            return 1
        if opname == "RETURN_VALUE":
            if is_module:
                if stack:
                    val = stack.pop()
                    if isinstance(val, ast.Constant) and val.value is None:
                        return 1
                return 1
            # Pop any leftover _ClosureRef values left by DUP_TOP/STORE_NAME
            # __classcell__ in class bodies; these are compiler artifacts.
            while stack and isinstance(stack[-1], _ClosureRef):
                stack.pop()
            if stack:
                val = stack.pop()
                stmts.append(ASTNode.make_Return(val))
            else:
                stmts.append(ASTNode.make_Return(None))
            return 1
        if opname in UNARY_OPS:
            if not stack:
                return 1
            operand = stack.pop()
            stack.append(ast.UnaryOp(op=UNARY_OPS[opname](), operand=operand))
            return 1
        if opname in BINARY_OPS:
            if len(stack) < 2:
                return 1
            right = stack.pop()
            left = stack.pop()
            stack.append(ast.BinOp(left=left, op=BINARY_OPS[opname](), right=right))
            return 1
        if opname in INPLACE_OPS:
            if len(stack) < 2:
                return 1
            right = stack.pop()
            target_expr = stack.pop()
            store_ctx = self._to_store_ctx(target_expr)
            if store_ctx is not None:
                stmts.append(ASTNode.make_AugAssign(store_ctx, INPLACE_OPS[opname](), right))
            else:
                stack.append(target_expr)
                stack.append(right)
            return 1
        if opname == "COMPARE_OP":
            if len(stack) < 2:
                return 1
            right = stack.pop()
            left = stack.pop()
            cmp_name = instr.argval
            op_type = COMPARE_OPS.get(cmp_name if isinstance(cmp_name, str) else "==", ast.Eq)
            stack.append(ast.Compare(left=left, ops=[op_type()], comparators=[right]))
            return 1
        if opname == "CONTAINS_OP":
            if len(stack) < 2:
                return 1
            container = stack.pop()
            value = stack.pop()
            op_type = ast.NotIn() if instr.arg else ast.In()
            stack.append(ast.Compare(left=value, ops=[op_type], comparators=[container]))
            return 1
        if opname == "BUILD_TUPLE":
            count = instr.arg or 0
            if len(stack) < count:
                return 1
            elts = []
            for _ in range(count):
                elts.insert(0, stack.pop())
            # Detect a closure tuple: all elements are _ClosureRef markers.
            if all(isinstance(e, _ClosureRef) for e in elts):
                self._current_closure = [e.name for e in elts]
                # Do not push the Tuple – it is a compiler artifact, not source.
                return 1
            stack.append(ast.Tuple(elts=elts, ctx=ast.Load()))
            return 1
        if opname == "BUILD_LIST":
            count = instr.arg or 0
            if len(stack) < count:
                return 1
            elts = []
            for _ in range(count):
                elts.insert(0, stack.pop())
            stack.append(ast.List(elts=elts, ctx=ast.Load()))
            return 1
        if opname == "BUILD_SET":
            count = instr.arg or 0
            if len(stack) < count:
                return 1
            elts = []
            for _ in range(count):
                elts.insert(0, stack.pop())
            stack.append(ast.Set(elts=elts))
            return 1
        if opname == "LIST_APPEND":
            # 3.9: the value is on top, the list sits ``arg`` slots below it, and
            # the value is discarded once appended.
            depth = instr.arg or 1
            if not stack:
                return 1
            value = stack.pop()
            if not stack:
                return 1
            target = stack[-depth] if -depth >= -len(stack) else stack[0]
            if isinstance(target, ast.List):
                target.elts.append(value)
            return 1
        if opname == "SET_ADD":
            depth = instr.arg or 1
            if not stack:
                return 1
            value = stack.pop()
            if not stack:
                return 1
            target = stack[-depth] if -depth >= -len(stack) else stack[0]
            if isinstance(target, ast.Set):
                target.elts.append(value)
            return 1
        if opname == "MAP_ADD":
            depth = instr.arg or 1
            if len(stack) < depth + 2:
                return 1
            value = stack.pop()
            key = stack.pop()
            target = stack[-depth] if -depth >= -len(stack) else stack[0]
            if isinstance(target, ast.Dict):
                target.keys.append(key)
                target.values.append(value)
            return 1
        if opname == "BUILD_MAP":
            count = instr.arg or 0
            if len(stack) < count * 2:
                return 1
            keys, vals = [], []
            for _ in range(count):
                vals.insert(0, stack.pop())
                keys.insert(0, stack.pop())
            stack.append(ast.Dict(keys=keys, values=vals))
            return 1
        if opname in ("DICT_MERGE", "DICT_UPDATE"):
            if not stack:
                return 1
            other = stack.pop()
            if not stack:
                return 1
            target = stack.pop()
            stack.append(_merge_dicts(target, other))
            return 1
        if opname in ("LIST_EXTEND", "SET_UPDATE"):
            if not stack:
                return 1
            other = stack.pop()
            if not stack:
                return 1
            target = stack.pop()
            elts = list(target.elts) if isinstance(target, (ast.List, ast.Set)) else []
            if isinstance(other, (ast.Tuple, ast.List, ast.Set)):
                elts.extend(other.elts)
            elif isinstance(other, ast.Constant) and isinstance(other.value, (tuple, list, set, frozenset)):
                elts.extend(ast.Constant(value=v) for v in other.value)
            else:
                # ``[a, *rest]`` spreads an arbitrary iterable, which only the
                # source form can express -- keep it as a starred element.
                elts.append(ast.Starred(value=other, ctx=ast.Load()))
            node = ast.List(elts=elts, ctx=ast.Load()) if isinstance(target, ast.List) else ast.Set(elts=elts)
            stack.append(node)
            return 1
        if opname == "BUILD_SLICE":
            count = instr.arg or 0
            if count == 2:
                if len(stack) < 2:
                    return 1
                stop = stack.pop()
                start = stack.pop()
                # An omitted bound compiles to ``LOAD_CONST None``; leaving that
                # in the tree prints ``s[None::-1]`` instead of ``s[::-1]``.
                start = _as_missing_bound(start)
                stop = _as_missing_bound(stop)
                stack.append(ast.Slice(lower=start, upper=stop, step=None))
            elif count == 3:
                if len(stack) < 3:
                    return 1
                step = stack.pop()
                stop = stack.pop()
                start = stack.pop()
                start = _as_missing_bound(start)
                stop = _as_missing_bound(stop)
                step = _as_missing_bound(step)
                stack.append(ast.Slice(lower=start, upper=stop, step=step))
            else:
                return 1
            return 1
        if opname == "BUILD_CONST_KEY_MAP":
            count = instr.arg or 0
            if len(stack) < count + 1:
                return 1
            keys_tuple = stack.pop()
            keys = []
            if isinstance(keys_tuple, ast.Constant) and isinstance(keys_tuple.value, tuple):
                for k in keys_tuple.value:
                    keys.append(ast.Constant(value=k))
            elif isinstance(keys_tuple, ast.Tuple):
                keys = list(keys_tuple.elts)
            else:
                for _ in range(count):
                    keys.append(ast.Constant(value="?"))
            vals = []
            for _ in range(count):
                if stack:
                    vals.insert(0, stack.pop())
                else:
                    vals.insert(0, ast.Constant(value=None))
            stack.append(ast.Dict(keys=keys, values=vals))
            return 1
        if opname == "BUILD_STRING":
            count = instr.arg or 0
            if len(stack) < count:
                return 1
            parts: List[ast.expr] = []
            for _ in range(count):
                parts.insert(0, stack.pop())
            stack.append(ast.JoinedStr(values=self._flatten_fstring_parts(parts)))
            return 1
        if opname == "FORMAT_VALUE":
            flags = instr.arg or 0
            conversion = flags & 0x3
            have_fmt = flags & 0x4
            fmt_spec = None
            if have_fmt and stack:
                fmt_spec = stack.pop()
            if not stack:
                return 1
            val = stack.pop()
            conv = {1: "s", 2: "r", 3: "a"}.get(conversion)
            stack.append(ast.JoinedStr(values=[ast.FormattedValue(
                value=val, conversion=ord(conv) if conv else -1, format_spec=fmt_spec
            )]))
            return 1
        if opname.startswith("CALL_FUNCTION") or opname in ("CALL_METHOD", "CALL_METHOD_KW", "CALL_KW"):
            return self._process_call(opname, instr, stack, stmts)
        if opname in ("MAKE_FUNCTION", "MAKE_CLOSURE"):
            return self._process_make_function(instr, stack, stmts, code)
        if opname in ("POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE", "JUMP_FORWARD", "JUMP_ABSOLUTE"):
            assert_consumed = self._try_emit_assert(
                instr, instructions, idx, code, stack, stmts, limit
            )
            if assert_consumed:
                return assert_consumed
            return self._process_jump(instr, instructions, idx, code, stack, stmts, limit=limit)
        if opname in ("SETUP_FINALLY", "SETUP_EXCEPT"):
            target = int(instr.argval if instr.argval is not None else (instr.arg or 0))
            # Pre-scan forward to find the POP_BLOCK that closes this try block
            try_end_idx = self._find_pop_block(instructions, idx, target)
            self._exc_stack.append({
                "except_target": target,
                "instr_start": idx,
                "try_end_idx": try_end_idx,
            })
            return 1
        if opname == "SETUP_WITH":
            return self._process_with(instr, instructions, idx, code, stack, stmts)
        if opname == "SETUP_ASYNC_WITH":
            return self._process_with(instr, instructions, idx, code, stack, stmts)
        if opname == "POP_BLOCK" and self._exc_stack and self._exc_stack[-1]["except_target"] is not None:
            block = self._exc_stack.pop()
            instr_start = block["instr_start"]
            target = block["except_target"]
            handler_start_idx = self._find_target_idx(instructions, target)
            try_end_idx = block["try_end_idx"]
            if try_end_idx <= instr_start or try_end_idx > handler_start_idx:
                try_end_idx = self._find_pop_block(instructions, instr_start, target)
            # A ``break``/``continue`` that leaves the body unwinds the block
            # and runs an inlined copy of the ``finally`` clause first.  That
            # copy belongs to the clause, not to the statement before the
            # exit, so hide it before the body is read -- otherwise it shows
            # up inside the ``if`` guarding the break.
            if self._is_bare_finally(instructions, handler_start_idx):
                clause_len = self._finally_clause_length(
                    instructions, handler_start_idx)
                if clause_len:
                    handler_copy = [
                        instructions[handler_start_idx + t].opname
                        for t in range(clause_len)
                    ]
                    for j in range(instr_start + 1, try_end_idx):
                        if instructions[j].opname != "POP_BLOCK":
                            continue
                        k = j + 1 + clause_len
                        while k + 1 < len(instructions) \
                                and instructions[k].opname in (
                                    "ROT_TWO", "ROT_THREE", "ROT_FOUR") \
                                and instructions[k + 1].opname == "POP_TOP":
                            k += 2
                        # Leaving a loop also drains its iterator.
                        if k < len(instructions) \
                                and instructions[k].opname == "POP_TOP":
                            k += 1
                        if k >= len(instructions) \
                                or instructions[k].opname not in (
                                    "JUMP_ABSOLUTE", "JUMP_FORWARD"):
                            continue
                        kind = self._classify_jump(
                            instructions, instructions[k])
                        if not isinstance(kind, (ast.Break, ast.Continue)):
                            continue
                        if [instructions[j + 1 + t].opname
                                for t in range(clause_len)] != handler_copy:
                            continue
                        self._handled_ranges.append((j + 1, k))
            try_stack: List[ast.expr] = []
            try_body = self._emit_statements(
                code, instructions, is_module=False, start=instr_start + 1, end=try_end_idx,
                out_stack=try_stack,
            )
            # When the try body consists solely of a ``return`` the compiler places
            # the ``POP_BLOCK`` *before* the ``LOAD_*`` / ``RETURN_VALUE`` (the pop
            # marks the protected range; the return sits just outside it).  In that
            # case the body above reads as a lone ``pass`` and the value on
            # ``try_stack`` is the return constant.  Detect that pattern and
            # re-emit past the POP_BLOCK so the return gets folded back in.
            _save_return_val: Optional[ast.expr] = None
            # When the try body consists solely of a ``return`` the compiler places
            # the ``POP_BLOCK`` *before* the ``LOAD_*`` / ``RETURN_VALUE`` (the pop
            # marks the protected range; the return sits just outside it).  In that
            # case the body above reads as a lone ``pass`` (or is empty for
            # try/except) and the value on ``try_stack`` may or may not have been
            # consumed.  Detect that pattern and re-emit past the POP_BLOCK so the
            # return gets folded back in.
            if (
                try_body == [ast.Pass()] or try_body == []
                and try_end_idx + 1 < len(instructions)
                and instructions[try_end_idx + 1].opname in (
                    "LOAD_CONST", "LOAD_FAST", "LOAD_NAME", "LOAD_GLOBAL",
                    "LOAD_DEREF", "LOAD_CLASSDEREF", "LOAD_CLOSURE",
                )
                and not try_stack
            ):
                # Only reach for a value past the ``POP_BLOCK`` when the body
                # itself left nothing on the stack.  A body that already pushed
                # its return value -- ``return n + 1`` compiled inside the
                # protected range -- must not have that expression re-read: the
                # instruction right after the pop is the ``finally`` clause, and
                # re-emitting from it would pile the clause onto the stack and
                # turn a correct ``return n + 1`` into a truncated ``return n``.
                # retfinally cases where RETURN_VALUE is still in range).
                _save_return_val = try_stack[-1] if try_stack else None
                # One extra instruction (LOAD_*); or two more if a loop-teardown
                # ROT_TWO/POP_TOP pair sits between load and return.
                extra = 1
                probe = try_end_idx + 2
                if (
                    probe + 1 < len(instructions)
                    and instructions[probe].opname in ("ROT_TWO", "ROT_THREE", "ROT_FOUR")
                    and instructions[probe + 1].opname == "POP_TOP"
                ):
                    extra = 3
                try_body = self._emit_statements(
                    code, instructions, is_module=False,
                    start=instr_start + 1, end=try_end_idx + extra + 1,
                    out_stack=try_stack,
                )
                # _emit_statements consumed the RETURN_VALUE and emptied
                # try_stack; put the saved value back so the block below can
                # decide whether to wrap it in ast.Return.
                if _save_return_val is not None and not try_stack:
                    try_stack.append(_save_return_val)
            elif (
                try_end_idx + 1 < len(instructions)
                and instructions[try_end_idx + 1].opname in (
                    "LOAD_CONST", "LOAD_FAST", "LOAD_NAME", "LOAD_GLOBAL",
                    "LOAD_DEREF", "LOAD_CLASSDEREF", "LOAD_CLOSURE",
                )
                and instructions[try_end_idx + 1].argval is not None
                and not try_stack
                and not self._is_bare_finally(instructions, handler_start_idx)
                and self._return_value_after_pop_block(
                    instructions, try_end_idx
                ) is not None
            ):
                # The body has statements of its own and ends with a
                # ``return`` whose value the compiler loaded *after* the block
                # pop -- a constant needs no work, so it is pushed afterwards.
                # The return is therefore not part of the body the reader has
                # seen, and reading it from there is the only way to keep it.
                #
                # A ``finally`` block is left out: the code behind its block
                # pop is whatever follows the whole ``try`` statement, not the
                # last statement of its body.  A ``return None`` is left out
                # too: it is indistinguishable from the implicit return the
                # compiler parks there.
                _return_idx = self._return_value_after_pop_block(
                    instructions, try_end_idx)
                tail = self._emit_statements(
                    code, instructions, is_module=False,
                    start=try_end_idx + 1, end=_return_idx + 1,
                    out_stack=[],
                )
                try_body.extend(tail)
            # A ``return`` as the last statement of a try body compiles to
            # ``POP_BLOCK`` + (optional loop-teardown pair) + ``RETURN_VALUE``;
            # the returned value is still on the virtual stack when the body
            # range ends.  When the try body is inside a loop, the compiler
            # emits ``ROT_TWO``/``POP_TOP`` between the ``POP_BLOCK`` and the
            # ``RETURN_VALUE`` to drain the loop iterator from the stack.
            if (
                try_stack
                and instructions[try_end_idx].opname == "POP_BLOCK"
                and self._is_return_after_pop_block(instructions, try_end_idx)
            ):
                try_body.append(ast.Return(value=try_stack.pop()))
            # A ``break`` as the last statement of a try body compiles to
            # ``POP_BLOCK`` + unconditional jump; ``_find_post_handler_idx`` skips
            # over that jump when it resumes after the handler, so recover it here.
            # A jump back to the loop head is the implicit back edge CPython emits
            # for normal try-body completion, not a source-level ``continue``.
            tail = try_end_idx + 1
            if tail < len(instructions) and instructions[tail].opname in (
                "JUMP_ABSOLUTE", "JUMP_FORWARD",
            ):
                tail_jump = self._classify_jump(instructions, instructions[tail])
                if isinstance(tail_jump, ast.Break):
                    try_body.append(tail_jump)
            if not try_body:
                try_body = [ast.Pass()]
            handlers: List[ast.ExceptHandler] = []
            orelse: List[ast.stmt] = []
            finalbody: List[ast.stmt] = []
            trailing: List[ast.stmt] = []
            parsed = self._parse_except_handlers(code, instructions,
                                                  handler_start_idx, try_end_idx)
            if parsed is None or self._is_bare_finally(instructions,
                                                       handler_start_idx):
                # ``SETUP_FINALLY`` whose handler only re-raises is a
                # ``try``/``finally``: the clause was emitted inline where the
                # protected range ends, and the handler runs a second copy of it
                # before propagating the exception.
                finalbody, resume = self._collect_finally_body(
                    code, instructions, try_end_idx, handler_start_idx
                )
                if not finalbody:
                    finalbody = [ast.Pass()]
                skip_to = resume
                if skip_to is None:
                    skip_to = self._find_post_handler_idx(
                        instructions, idx, handler_start_idx, target)
                cont, skip_to = self._continue_over_handler(instructions, skip_to)
                if cont is not None:
                    trailing.append(cont)
                else:
                    skip_to = self._consume_back_edge(instructions, skip_to)
                    if self._is_return_after_finally(
                        instructions, resume
                    ) and len(try_body) == 1 and isinstance(try_body[0], ast.Pass):
                        # A ``return`` that is the last statement of an otherwise
                        # empty body is compiled *after* the inline finally copy, so
                        # it is left outside the ``try`` and reads as a statement
                        # that never runs.  Pull it back into the body.  A body that
                        # already has statements is left alone: there the return may
                        # belong to a nested block, and lifting it would duplicate
                        # it.
                        if instructions[resume].opname == "RETURN_VALUE":
                            # The body left the value on the stack.
                            try_body = [ast.Return(value=try_stack.pop() if try_stack else None)]
                        else:
                            tail = self._emit_statements(
                                code, instructions, is_module=False, start=resume,
                                end=resume + 2, out_stack=[],
                            )
                            if tail:
                                try_body = tail
                        skip_to = resume + 2
                    elif self._is_return_after_finally(
                        instructions, resume
                    ) and len(try_body) == 1 and isinstance(try_body[0], ast.Try):
                        # Nested ``try``/``finally``: the protected body is itself
                        # a ``try``/``finally`` whose body collapsed to ``pass``
                        # because the compiler deferred the ``return`` past *every*
                        # enclosing finally clause's inline copy.  That deferred
                        # ``return`` belongs to the *innermost* empty try body, so
                        # descend the single-Try chain and put it back there.
                        # ``try: pass`` nested under a real ``try`` looks identical
                        # on the bytecode level, so this only fires when the
                        # innermost body is genuinely empty (``pass``): a nested
                        # try whose body carries statements keeps its hoisted
                        # return at this level.
                        if instructions[resume].opname == "RETURN_VALUE":
                            ret = ast.Return(
                                value=try_stack.pop() if try_stack else None)
                        else:
                            tail = self._emit_statements(
                                code, instructions, is_module=False, start=resume,
                                end=resume + 2, out_stack=[],
                            )
                            ret = tail[0] if tail else ast.Return(value=None)
                        inner_body = try_body[0].body
                        while len(inner_body) == 1 and isinstance(inner_body[0], ast.Try):
                            inner_body = inner_body[0].body
                        if not inner_body or (
                            len(inner_body) == 1
                            and isinstance(inner_body[0], ast.Pass)
                        ):
                            inner_body[:] = [ret]
                            skip_to = resume + 2
            else:
                handlers, orelse, post = parsed
                if not orelse:
                    orelse = self._recover_else_clause(
                        code, instructions, try_end_idx, handler_start_idx, post)
                skip_to = post
            stmts.append(ast.Try(body=try_body, handlers=handlers, orelse=orelse,
                                 finalbody=finalbody))
            stmts.extend(trailing)
            return max(1, skip_to - idx)
        if opname == "RERAISE":
            reraise_arg = instr.arg or 0
            if reraise_arg == 0:
                # The compiler closes every ``except`` chain with a bare
                # ``RERAISE`` that propagates the caught exception when no
                # clause matched.  It has no source form -- a ``raise`` the
                # programmer wrote compiles to ``RAISE_VARARGS 0`` -- so
                # emitting it adds a stray, unreachable statement to whichever
                # clause body happens to contain it.
                return 1
            # Pop exception (and optionally cause) from stack
            args = []
            for _ in range(reraise_arg):
                if stack:
                    args.insert(0, stack.pop())
            exc = args[0] if args else None
            cause = args[1] if len(args) >= 2 else None
            stmts.append(ast.Raise(exc=exc, cause=cause))
            return 1
        if opname in ("POP_EXCEPT", "PUSH_EXC_INFO", "CHECK_EXC_MATCH", "WITH_EXCEPT_START"):
            return 1
        if opname in ("JUMP_IF_NOT_EXC_MATCH", "CHECK_EG_MATCH", "JUMP_IF_NOT_EG_MATCH"):
            return self._process_safe_jump(instr)
        if opname in ("END_FOR", "END_SEND", "CLEANUP_THROW", "CLEANUP_FINALLY"):
            return 1
        if opname in ("FOR_ITER", "GET_ITER"):
            return self._process_loop(instr, instructions, idx, code, stack, stmts, limit=limit)
        if opname == "GET_AITER":
            return self._process_async_for(
                instr, instructions, idx, code, stack, stmts, limit=limit
            )
        if opname == "GET_YIELD_FROM_ITER":
            return self._process_yield_from(
                instr, instructions, idx, code, stack, stmts, limit=limit
            )
        if opname == "GET_AWAITABLE":
            return self._process_yield_from(
                instr, instructions, idx, code, stack, stmts, limit=limit,
                node=ast.Await,
            )
        if opname == "BEFORE_ASYNC_WITH":
            # The context expression stays on the stack for the ``SETUP_ASYNC_WITH``
            # that follows the ``__aenter__`` await, so skip that await here.
            j = idx + 1
            if j < len(instructions) and instructions[j].opname == "GET_AWAITABLE":
                j += 1
                if j < len(instructions) and instructions[j].opname == "LOAD_CONST":
                    j += 1
                if j < len(instructions) and instructions[j].opname == "YIELD_FROM":
                    j += 1
            return max(1, j - idx)
        if opname == "SETUP_LOOP":
            return 1
        if opname == "IMPORT_NAME":
            mod_name = str(instr.argval)
            # The two operands below the module name are ``fromlist`` and
            # ``level``.  ``level`` is the number of leading dots in a relative
            # import, and dropping it silently turns ``from ..pkg import x``
            # into an absolute import that resolves somewhere else entirely.
            fromlist = stack[-1] if stack else None
            level = 0
            if len(stack) >= 2 and isinstance(stack[-2], ast.Constant) \
                    and isinstance(stack[-2].value, int):
                level = int(stack[-2].value)
            self._import_ctx_module = mod_name
            self._import_ctx_level = level
            # A non-empty fromlist means this is a ``from mod import ...``; the
            # following IMPORT_FROM emits that statement, so a bare ``import mod``
            # here would duplicate it.  Both operands stay on the stack, so drop
            # them before pushing the imported module.
            is_from_import = (
                isinstance(fromlist, ast.Constant)
                and isinstance(fromlist.value, tuple)
                and len(fromlist.value) > 0
            )
            for _ in range(2):
                if stack:
                    stack.pop()
            stack.append(ASTNode.make_Name(mod_name, ast.Load()))
            # Only emit import statement if not inside a try block and not already emitted
            if (
                not self._exc_stack and not is_from_import
                and mod_name not in self._imported_modules
            ):
                stmts.append(ast.Import(names=[ast.alias(name=mod_name, asname=None)]))
                self._imported_modules.add(mod_name)
            return 1
        if opname == "IMPORT_FROM":
            name_str = str(instr.argval)
            # Use the tracked module context instead of scanning the stack.
            # ``self._import_ctx_module is not None`` rather than a truth test:
            # a relative import has an empty module name.
            if self._import_ctx_module is not None:
                if not self._exc_stack:
                    self._pending_from_names.append((name_str, None))
                stack.append(ast.Name(id=name_str, ctx=ast.Load()))
                return 1
            stack.append(ast.Name(id=name_str, ctx=ast.Load()))
            return 1
        if opname == "IMPORT_STAR":
            if not stack:
                return 1
            mod = stack.pop()
            mod_id = mod.id if isinstance(mod, ast.Name) else "*"
            stmts.append(ast.ImportFrom(module=mod_id, names=[ast.alias(name="*", asname=None)], level=0))
            return 1
        if opname == "DELETE_FAST":
            target = ASTNode.make_Name(str(instr.argval), ast.Del())
            stmts.append(ast.Delete(targets=[target]))
            return 1
        if opname == "DELETE_NAME":
            target = ASTNode.make_Name(str(instr.argval), ast.Del())
            stmts.append(ast.Delete(targets=[target]))
            return 1
        if opname == "DELETE_ATTR":
            if not stack:
                return 1
            obj = stack.pop()
            stmts.append(ast.Delete(targets=[
                ast.Attribute(value=obj, attr=str(instr.argval), ctx=ast.Del())]))
            return 1
        if opname == "DELETE_SUBSCR":
            if len(stack) < 2:
                return 1
            key = stack.pop()
            obj = stack.pop()
            stmts.append(ast.Delete(targets=[
                ast.Subscript(value=obj, slice=key, ctx=ast.Del())]))
            return 1
        if opname == "YIELD_VALUE":
            val = stack.pop() if stack else None
            nxt = idx + 1
            limit_idx = len(instructions) if limit is None else limit
            if (
                nxt < limit_idx
                and instructions[nxt].opname in self._IFEXP_STORE_OPS
            ):
                # ``t = yield v`` -- whatever is sent back in is stored right
                # after the suspension point.
                stmts.append(
                    ASTNode.make_Assign(
                        [ASTNode.make_Name(str(instructions[nxt].argval), ast.Store())],
                        ast.Yield(value=val),
                    )
                )
                return 2
            stmts.append(ast.Expr(value=ast.Yield(value=val)))
            return 1
        if opname == "RAISE_VARARGS":
            argc = instr.arg or 0
            args = []
            for _ in range(argc):
                if stack:
                    args.insert(0, stack.pop())
            exc = args[0] if args else None
            cause = None
            if argc >= 2:
                cause = args[1]
            stmts.append(ast.Raise(exc=exc, cause=cause))
            return 1
        if opname == "NOP":
            return 1
        if opname == "RESUME":
            return 1
        if opname == "DUP_TOP" or (opname == "COPY" and (instr.arg or 1) == 1):
            if not stack:
                return 1
            limit_idx = len(instructions) if limit is None else limit
            dup_op = "DUP_TOP" if opname == "DUP_TOP" else "COPY"
            nxt = instructions[idx + 1] if idx + 1 < limit_idx else None
            if (
                nxt is not None
                and nxt.opname in self._STORE_OPS
                and nxt.argval != "__classcell__"
            ):
                # ``a = b = 1`` compiles to one duplication per extra target --
                # ``DUP_TOP`` on 3.9, ``COPY 1`` from 3.11 on -- so the stores
                # that follow, not the expression itself, decide how many names
                # are being bound.  ``(y := value)`` has exactly one store and
                # then *uses* the value, which is what told the two apart here
                # before: reading any duplicate that happens to precede a store
                # as a walrus turns ``a = b = 1`` into ``b = (a := 1)``.
                targets: List[ast.expr] = []
                j = idx + 1
                consumed = 1
                while (
                    j < limit_idx
                    and instructions[j].opname in self._STORE_OPS
                    and instructions[j].argval != "__classcell__"
                ):
                    target, nxt_idx = self._parse_store_target(instructions, j)
                    if target is None:
                        break
                    targets.append(target)
                    consumed = nxt_idx - idx
                    j = nxt_idx
                    if j < limit_idx and instructions[j].opname == dup_op:
                        j += 1
                        consumed += 1
                if len(targets) >= 2:
                    value = stack[-1]
                    del stack[-1]
                    stmts.append(ast.Assign(targets=targets, value=value))
                    return consumed
                # ``(y := value)`` duplicates the value so it survives the
                # assignment that follows, which no plain store ever does.
                # ``__classcell__`` is emitted by the compiler for ``__class__``
                # and has no source form.
                stack[-1] = ast.NamedExpr(
                    target=ASTNode.make_Name(str(nxt.argval), ast.Store()),
                    value=stack[-1],
                )
                return 2
            stack.append(stack[-1])
            return 1
        if opname == "DUP_TOP_TWO":
            if len(stack) >= 2:
                stack.extend(stack[-2:])
            return 1
        if opname == "ROT_TWO":
            # ``a, b = x, y`` compiles to two pushes, ``ROT_TWO`` and two stores;
            # collapse that back into a single tuple assignment.
            if len(stack) == 2:
                targets, end = self._collect_store_targets(instructions, idx + 1, 2)
                if len(targets) == 2:
                    pair = ast.Tuple(elts=[stack[-2], stack[-1]], ctx=ast.Load())
                    del stack[-2:]
                    stmts.append(
                        ASTNode.make_Assign(
                            [ast.Tuple(elts=targets, ctx=ast.Store())], pair
                        )
                    )
                    return end - idx
            if len(stack) >= 2:
                stack[-1], stack[-2] = stack[-2], stack[-1]
            return 1
        if opname == "ROT_THREE":
            consumed = self._try_emit_parallel_assign(
                instructions, idx, stack, stmts
            )
            if consumed:
                return consumed
            if len(stack) >= 3:
                stack[-3:] = [stack[-1], stack[-3], stack[-2]]
            return 1
        if opname == "ROT_N":
            n = instr.arg or 0
            if n >= 2 and len(stack) >= n:
                top = stack[-1]
                for k in range(n - 1, 0, -1):
                    stack[-(k + 1)] = stack[-k]
                stack[-1] = top
            return 1
        if opname == "RETURN_CONST":
            stmts.append(ASTNode.make_Return(self._make_constant(instr.argval)))
            return 1
        if opname == "COPY":
            n = instr.arg or 1
            if len(stack) >= n:
                stack.append(stack[-n])
            return 1
        if opname == "SWAP":
            n = instr.arg or 2
            if len(stack) >= n:
                stack[-1], stack[-n] = stack[-n], stack[-1]
            return 1
        if opname == "CACHE":
            return 1
        if stack:
            return 1
        return 1

    def _flatten_fstring_parts(self, parts: List[ast.expr]) -> List[ast.expr]:
        """Flatten the operands of ``BUILD_STRING`` into ``JoinedStr.values``.

        The compiler pushes a *nested* ``JoinedStr`` for every ``FORMAT_VALUE`` and
        for the literal chunks around it, so ``f"a{b}c"`` reaches us as
        ``[Const('a'), JoinedStr([b]), Const('c')]``.  Inlining the nested nodes
        and merging adjacent literals yields the exact original field layout.
        """
        flat: List[ast.expr] = []
        for part in parts:
            self._inline_fstring_part(part, flat)
        merged: List[ast.expr] = []
        for node in flat:
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and merged
                and isinstance(merged[-1], ast.Constant)
                and isinstance(merged[-1].value, str)
            ):
                merged[-1] = ast.Constant(value=merged[-1].value + node.value)
            else:
                merged.append(node)
        return merged

    def _inline_fstring_part(self, part: ast.expr, out: List[ast.expr]) -> None:
        """Append ``part`` to ``out``, expanding nested JoinedStr / ``+`` chains."""
        if isinstance(part, ast.JoinedStr):
            for value in part.values:
                self._inline_fstring_part(value, out)
            return
        # A single-element f-string such as f"{x}" is a JoinedStr wrapping one
        # FormattedValue; BUILD_STRING then receives it as a plain operand.
        if (
            isinstance(part, ast.BinOp)
            and isinstance(part.op, ast.Add)
            and self._is_fstring_operand(part.left)
            and self._is_fstring_operand(part.right)
        ):
            self._inline_fstring_part(part.left, out)
            self._inline_fstring_part(part.right, out)
            return
        if isinstance(part, ast.FormattedValue):
            out.append(part)
            return
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            out.append(ast.Constant(value=part.value))
            return
        if isinstance(part, ast.Constant):
            out.append(ast.Constant(value=str(part.value)))
            return
        out.append(ast.FormattedValue(value=part, conversion=-1, format_spec=None))

    def _is_fstring_operand(self, node: ast.expr) -> bool:
        """True for nodes that belong inside an f-string field sequence."""
        if isinstance(node, (ast.JoinedStr, ast.FormattedValue)):
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return True
        return isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)

    def _kw_names_from(self, node: ast.expr) -> List[str]:
        """Extract keyword names from the tuple pushed for ``CALL_FUNCTION_KW``.

        CPython pushes the names as a single constant, so the node is an
        ``ast.Constant`` wrapping a tuple of strings.
        """
        if isinstance(node, ast.Tuple):
            values = [e.value for e in node.elts]
        elif isinstance(node, ast.Constant) and isinstance(node.value, tuple):
            values = list(node.value)
        else:
            return []
        return [v if isinstance(v, str) else "kw" for v in values]

    def _build_class_def(
        self,
        args: List[ast.expr],
        stmts: List[ast.stmt],
        keywords: Optional[List[ast.keyword]] = None,
    ) -> bool:
        """Turn a ``__build_class__`` call into a ``ClassDef``.

        CPython compiles ``class C(Bases, metaclass=M)`` into a call to the
        ``__build_class__`` helper whose arguments are ``body, name, *bases``
        followed by any class keywords.  Returns ``False`` when *args* is not
        that shape, leaving the caller to fall back to a plain call.
        """
        if len(args) < 2:
            return False
        class_code_const = args[0]
        class_name_node = args[1]
        bases = list(args[2:])
        class_name = "Class"
        if isinstance(class_name_node, ast.Constant) and isinstance(class_name_node.value, str):
            class_name = class_name_node.value

        def _drop_implicit_return(entries: List[ast.stmt]) -> List[ast.stmt]:
            return [
                s for s in entries
                if not (
                    isinstance(s, ast.Return)
                    and (
                        s.value is None
                        or (isinstance(s.value, ast.Constant) and s.value.value is None)
                        or (isinstance(s.value, ast.Name) and s.value.id == "__class__")
                    )
                )
            ]

        body_stmts: List[ast.stmt] = []
        if isinstance(class_code_const, _FuncDefHolder):
            body_stmts = _drop_implicit_return(list(class_code_const.func_def.body))
        elif isinstance(class_code_const, ast.Constant) and hasattr(class_code_const.value, "co_code"):
            try:
                instrs = self.dis.disassemble(class_code_const.value)
                with self._isolated_state():
                    body_stmts = self._emit_statements_safe(
                        class_code_const.value, instrs, is_module=False
                    )
                body_stmts = _drop_implicit_return(body_stmts)
            except Exception:
                body_stmts = [ast.Expr(value=ast.Constant(value="# class body"))]
        else:
            return False

        body_stmts = self._strip_class_artifacts(body_stmts)
        body_stmts = self._restore_docstring(body_stmts)
        if not body_stmts:
            body_stmts = [ast.Pass()]
        stmts.append(ast.ClassDef(
            name=class_name, bases=bases, keywords=list(keywords or []),
            body=body_stmts, decorator_list=[],
        ))
        return True

    def _holder_to_expr(self, holder: "_FuncDefHolder") -> ast.expr:
        """Render a function object as an expression (used for ``@lambda``)."""
        holder.apply_extras()
        fn = holder.func_def
        if len(fn.body) == 1 and isinstance(fn.body[0], ast.Return):
            return ast.Lambda(args=fn.args, body=fn.body[0].value)
        return fn

    def _process_call(self, opname: str, instr: Instruction, stack: List[ast.expr], stmts: List[ast.stmt]) -> int:
        if opname == "CALL_FUNCTION":
            argc = instr.arg or 0
            if len(stack) < argc + 1:
                return 1
            args = []
            for _ in range(argc):
                args.insert(0, stack.pop())
            func = stack.pop()
            if isinstance(func, _CompMaker) and argc == 1:
                comp = self._build_comprehension(func.code_obj, args[0])
                if comp is not None:
                    stack.append(comp)
                    return 1
            if argc == 1 and isinstance(args[0], _FuncDefHolder):
                # ``@deco`` compiles to ``deco(MAKE_FUNCTION(...))``
                if isinstance(func, _FuncDefHolder):
                    func = self._holder_to_expr(func)
                args[0].func_def.decorator_list.insert(0, func)
                stack.append(args[0])
                return 1
            if isinstance(func, ast.Name) and func.id == "__build_class__" and argc >= 2:
                if self._build_class_def(args, stmts):
                    return 1
            stack.append(ASTNode.make_Call(func, args))
            return 1
        if opname == "CALL_FUNCTION_KW":
            argc = instr.arg or 0
            if len(stack) < argc + 2:
                return 1
            kw_tuple = stack.pop()
            kw_names = self._kw_names_from(kw_tuple)
            args = []
            for _ in range(argc):
                args.insert(0, stack.pop())
            func = stack.pop()
            num_kw = len(kw_names)
            pos_args = args[:argc - num_kw]
            kw_args = args[argc - num_kw:]
            keywords = [ast.keyword(arg=n, value=v) for n, v in zip(kw_names, kw_args)]
            # ``class C(Base, metaclass=M)`` compiles to ``__build_class__``
            # with keywords, so the class special case has to run here too --
            # otherwise the class body leaks out as a bare code object constant.
            if isinstance(func, ast.Name) and func.id == "__build_class__" and len(pos_args) >= 2:
                if self._build_class_def(pos_args, stmts, keywords):
                    return 1
            stack.append(ASTNode.make_Call(func, pos_args, keywords))
            return 1
        if opname == "CALL_FUNCTION_EX":
            # 3.9 layout: [func, args] or [func, args, kwargs] -> [result]
            flags = instr.arg or 0
            if len(stack) < 2:
                return 1
            kwargs = None
            if flags & 1:
                if len(stack) < 3:
                    return 1
                kwargs = stack.pop()
            args_ast = stack.pop()
            func = stack.pop()
            args_list = []
            kw_list = []
            if isinstance(args_ast, (ast.Tuple, ast.List)):
                args_list = list(args_ast.elts)
            else:
                args_list.append(ast.Starred(value=args_ast, ctx=ast.Load()))
            if kwargs is not None:
                if isinstance(kwargs, ast.Dict):
                    for k, v in zip(kwargs.keys, kwargs.values):
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            kw_list.append(ast.keyword(arg=k.value, value=v))
                        else:
                            kw_list.append(ast.keyword(arg=None, value=v))
                else:
                    kw_list.append(ast.keyword(arg=None, value=kwargs))
            stack.append(ASTNode.make_Call(func, args_list, kw_list))
            return 1
        if opname == "CALL_METHOD_KW":
            # 3.9 layout: [obj, method, arg1..argN, kw_names] -> [result]
            argc = instr.arg or 0
            if len(stack) < argc + 3:
                return 1
            kw_names = self._kw_names_from(stack.pop())
            args = []
            for _ in range(argc):
                args.insert(0, stack.pop())
            method = stack.pop()
            obj = stack.pop()
            if isinstance(method, _MethodRef):
                func = ast.Attribute(value=obj, attr=method.name, ctx=ast.Load())
            else:
                func = method
            num_kw = len(kw_names)
            keywords = [
                ast.keyword(arg=n, value=v)
                for n, v in zip(kw_names, args[argc - num_kw:])
            ]
            stack.append(ASTNode.make_Call(func, args[:argc - num_kw], keywords))
            return 1
        if opname == "CALL_METHOD":
            # 3.9 layout: [obj, method, arg1..argN] -> [result]
            argc = instr.arg or 0
            if len(stack) < argc + 2:
                return 1
            args = []
            for _ in range(argc):
                args.insert(0, stack.pop())
            method = stack.pop()
            obj = stack.pop()
            if isinstance(method, _MethodRef):
                func = ast.Attribute(value=obj, attr=method.name, ctx=ast.Load())
            elif isinstance(method, ast.Name):
                func = ast.Attribute(value=obj, attr=method.id, ctx=ast.Load())
            else:
                func = method
            stack.append(ASTNode.make_Call(func, args))
            return 1
        return 1

    def _process_make_function(self, instr: Instruction, stack: List[ast.expr], stmts: List[ast.stmt], code) -> int:
        """Pop the operands of ``MAKE_FUNCTION`` and rebuild a ``FunctionDef``.

        Python 3.9–3.10 pushes the ``co_name``/``co_qualname`` string as the
        topmost operand; Python 3.11+ only pushes the code object itself
        (the name is read from ``co_name`` later).  The remaining flags are
        ``0x01`` defaults, ``0x02`` kwdefaults, ``0x04`` annotations and
        ``0x08`` closure; the closure tuple sits *below* the code object, so it
        is popped last.
        """
        flags = instr.arg or 0
        if not stack:
            return 1
        top = stack.pop()
        # Python 3.11+: top is the code object directly (wrapped in ast.Constant).
        # Python 3.9–3.10: top is the name string; the code object follows.
        if isinstance(top, ast.Constant) and hasattr(top.value, "co_code"):
            # Python 3.11+ — code object is on top, no separate name operand.
            func_code_obj = top.value
            func_name = func_code_obj.co_name
            func_code = top
        else:
            # Python 3.9–3.10 — name string is on top, code object below.
            name = top
            if not stack:
                return 1
            func_code = stack.pop()
            func_name = "lambda"
            if isinstance(name, ast.Constant) and isinstance(name.value, str):
                func_name = name.value.rsplit(".", 1)[-1]
        annotations = None
        kw_defaults = None
        pos_defaults = None
        closure = None
        for flag, attr in ((0x04, "annotations"), (0x02, "kw_defaults"), (0x01, "pos_defaults")):
            if not flags & flag:
                continue
            if not stack:
                return 1
            value = stack.pop()
            if attr == "annotations":
                annotations = value
            elif attr == "kw_defaults":
                kw_defaults = value
            else:
                pos_defaults = value
        if flags & 0x08:
            # Closure tuple was consumed by BUILD_TUPLE and not pushed to the stack.
            # Use the recorded closure names directly.
            closure = self._current_closure or None
            self._current_closure = None
        if isinstance(func_code, ast.Constant) and hasattr(func_code.value, "co_code"):
            # Propagate closure free-var names into the nested code object's context.
            if self._current_closure is not None:
                self._closure_names = set(self._current_closure)
                self._current_closure = None
            if func_code.value.co_name in ("<listcomp>", "<setcomp>", "<dictcomp>", "<genexpr>"):
                stack.append(_CompMaker(func_code.value))
                return 1
            fn = self._decompile_function(func_code.value, func_name)
            holder = _FuncDefHolder(fn, annotations=annotations, defaults=pos_defaults, kw_defaults=kw_defaults, closure=closure)
            if func_name in ("lambda", "<lambda>") or getattr(func_code.value, "co_name", None) == "<lambda>":
                stack.append(self._holder_to_expr(holder))
            else:
                stack.append(holder)
            return 1
        stack.append(ast.Name(id=f"<function {func_name}>", ctx=ast.Load()))
        return 1

    def _build_comprehension(self, code_obj, iterable: ast.expr) -> Optional[ast.expr]:
        """Rebuild a list/set/dict comprehension or generator expression.

        The nested code object takes the outer iterable as its ``.0`` argument.
        A comprehension with several ``for`` clauses runs one ``FOR_ITER`` loop
        per clause, nested: each loop head is the target of the ``JUMP_ABSOLUTE``
        that closes it, and the loop that jumps to an *outer* head ends the
        clause it belongs to.  Optional ``if`` guards pop a condition and jump
        back to the head of the loop they filter.  The element (or key/value
        pair) is what remains on the stack when ``LIST_APPEND`` / ``SET_ADD`` /
        ``MAP_ADD`` fires.
        """
        try:
            # Comprehensions may close over outer variables (e.g. lambda defaults
            # or enclosing-function locals).  Inherit the current closure set.
            old_closure = self._closure_names
            self._closure_names = old_closure
            # Save exc_stack depth to prevent SETUP_FINALLY entries from the
            # inner code object from leaking onto the host stack.
            old_exc_depth = len(self._exc_stack)
            instrs = self.dis.disassemble(code_obj)
        except Exception:
            return None
        generators: List[ast.comprehension] = []
        heads: List[int] = []
        element: Optional[ast.expr] = None
        key: Optional[ast.expr] = None
        stack: List[ast.expr] = []
        scratch: List[ast.stmt] = []
        i = 0
        pending_iter: List[ast.expr] = [iterable]
        while i < len(instrs):
            ins = instrs[i]
            opname = ins.opname
            if opname == "FOR_ITER":
                clause = self._open_comprehension_clause(
                    instrs, i, generators, heads, pending_iter, stack
                )
                if clause is None:
                    break
                i = clause
                continue
            if opname == "GET_ANEXT":
                clause = self._open_comprehension_clause(
                    instrs, i, generators, heads, pending_iter, stack,
                    is_async=True,
                )
                if clause is None:
                    break
                i = clause
                continue
            if opname in ("POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE"):
                depth = self._back_edge_depth(instrs, i, heads)
                if depth is None or not stack:
                    break
                cond = stack.pop()
                if opname == "POP_JUMP_IF_TRUE":
                    cond = ast.UnaryOp(op=ast.Not(), operand=cond)
                # The guard filters the clause whose loop head it jumps back to.
                generators[depth].ifs.append(cond)
                i += 1
                continue
            if opname in ("LIST_APPEND", "SET_ADD", "YIELD_VALUE"):
                if not stack:
                    break
                element = stack.pop()
                i += 1
                continue
            if opname == "MAP_ADD":
                if len(stack) < 2:
                    break
                element = stack.pop()
                key = stack.pop()
                i += 1
                continue
            if opname in ("JUMP_ABSOLUTE", "JUMP_FORWARD"):
                if self._back_edge_depth(instrs, i, heads) is None:
                    break
                i += 1
                continue
            if opname in ("RETURN_VALUE", "RETURN_CONST"):
                break
            consumed = self._process_instruction(
                ins, instrs, i, code_obj, stack, scratch, is_module=False,
            )
            i += consumed if consumed else 1

        if element is None or not generators:
            self._closure_names = old_closure
            self._exc_stack[:] = self._exc_stack[:old_exc_depth]
            return None
        name = code_obj.co_name
        if name == "<listcomp>":
            node = ast.ListComp(elt=element, generators=generators)
        elif name == "<setcomp>":
            node = ast.SetComp(elt=element, generators=generators)
        elif name == "<genexpr>":
            node = ast.GeneratorExp(elt=element, generators=generators)
        elif name == "<dictcomp>" and key is not None:
            node = ast.DictComp(key=key, value=element, generators=generators)
        else:
            node = None
        self._closure_names = old_closure
        self._exc_stack[:] = self._exc_stack[:old_exc_depth]
        return node

    def _open_comprehension_clause(
        self,
        instrs: List[Instruction],
        idx: int,
        generators: List[ast.comprehension],
        heads: List[int],
        pending_iter: List[ast.expr],
        stack: List[ast.expr],
        is_async: bool = False,
    ) -> Optional[int]:
        """Start one ``for`` clause of a comprehension at the ``FOR_ITER`` *idx*.

        The outermost clause iterates the ``.0`` argument; a nested one iterates
        whatever the enclosing body left on the stack.  The clause's loop head is
        recorded in *heads* so its guards and its back edge can be recognised
        later.  Returns the index just past the clause's target stores, or
        ``None`` when the shape is not recognised.

        An ``async for`` clause is anchored on its ``GET_ANEXT``, preceded by the
        3.9 ``SETUP_FINALLY`` the back edge returns to and by the
        ``LOAD_CONST``/``YIELD_FROM``/``POP_BLOCK`` that await the next item.
        """
        if generators:
            # ``GET_ITER`` pushed the nested iterable before the ``FOR_ITER``;
            # it is the only value the enclosing body produced for this clause.
            if not stack:
                return None
            source = stack.pop()
        else:
            if not pending_iter:
                return None
            source = pending_iter[0]
        head = idx
        stores = idx + 1
        if is_async:
            stores = idx + 1
            if instrs[stores].opname == "LOAD_CONST":
                stores += 1
            if stores < len(instrs) and instrs[stores].opname == "YIELD_FROM":
                stores += 1
            if stores < len(instrs) and instrs[stores].opname == "POP_BLOCK":
                stores += 1
            head = idx - 1 if idx and instrs[idx - 1].opname == "SETUP_FINALLY" \
                else idx
        targets, body_start = self._collect_store_targets(instrs, stores, 1)
        if len(targets) != 1:
            return None
        target = targets[0]
        # ``for a, b in it`` unpacks into a tuple target.
        if instrs[stores].opname == "UNPACK_SEQUENCE":
            count = instrs[stores].arg or 0
            unpacked, body_start = self._collect_store_targets(
                instrs, stores + 1, count
            )
            if len(unpacked) != count:
                return None
            target = ast.Tuple(elts=unpacked, ctx=ast.Store())
        generators.append(
            ast.comprehension(target=target, iter=source, ifs=[],
                              is_async=1 if is_async else 0)
        )
        heads.append(instrs[head].offset)
        pending_iter.clear()
        return body_start

    @staticmethod
    def _back_edge_depth(instrs, idx, heads: List[int]) -> Optional[int]:
        """Index of the clause whose loop head the jump at *idx* targets."""
        target = instrs[idx].argval
        if target is None:
            return None
        for depth, head in enumerate(heads):
            if head == target:
                return depth
        return None

    def _decompile_function(self, func_code, func_name: Optional[str]) -> ast.FunctionDef:
        if func_name is None:
            func_name = func_code.co_name
        args = self._build_arguments(func_code)
        decorators: List[ast.expr] = []
        returns = None
        # Save/restore outer closure names so this function's MAKE_FUNCTION
        # processing can override them without leaking out.
        old_closure = self._closure_names
        self._closure_names = None
        instrs = self.dis.disassemble(func_code)
        # Instruction ranges are indices into one code object, so the enclosing
        # function's must not hide instructions of this one.
        old_handled = self._handled_ranges
        self._handled_ranges = []
        body_stmts = self._emit_statements_safe(func_code, instrs)
        self._handled_ranges = old_handled
        self._closure_names = old_closure
        body_stmts = self._drop_dead_tail(body_stmts)
        body_stmts = self._prepend_function_docstring(func_code, instrs, body_stmts)
        body_stmts = self._restore_scope_declarations(func_code, instrs, body_stmts)
        if not body_stmts:
            body_stmts = [ast.Pass()]
        # CO_COROUTINE (0x80) marks a plain coroutine, CO_ASYNC_GENERATOR
        # (0x200) an ``async def`` that also yields; both need the ``async``
        # keyword on the definition itself.
        flags = getattr(func_code, "co_flags", 0)
        cls = ast.AsyncFunctionDef if flags & (0x80 | 0x200) else ast.FunctionDef
        fn = cls(
            name=func_name,
            args=args,
            body=body_stmts,
            decorator_list=decorators,
            returns=returns,
        )
        return fn

    def _build_arguments(self, func_code) -> ast.arguments:
        argcount = getattr(func_code, "co_argcount", 0)
        kwonlyargcount = getattr(func_code, "co_kwonlyargcount", 0)
        posonlyargcount = getattr(func_code, "co_posonlyargcount", 0)
        varnames = list(getattr(func_code, "co_varnames", ()))
        flags = getattr(func_code, "co_flags", 0)
        vararg = None
        kwarg = None
        if flags & 0x04:
            idx = argcount + kwonlyargcount
            if idx < len(varnames):
                vararg = varnames[idx]
                idx += 1
        if flags & 0x08:
            if flags & 0x04:
                idx = argcount + kwonlyargcount + 1
            else:
                idx = argcount + kwonlyargcount
            if idx < len(varnames):
                kwarg = varnames[idx]
        posonly_args = []
        regular_args = []
        for i in range(posonlyargcount):
            if i < len(varnames):
                posonly_args.append(ast.arg(arg=varnames[i]))
        for i in range(posonlyargcount, argcount):
            if i < len(varnames):
                regular_args.append(ast.arg(arg=varnames[i]))
        kwonly_args = []
        for i in range(argcount, argcount + kwonlyargcount):
            if i < len(varnames):
                kwonly_args.append(ast.arg(arg=varnames[i]))
        defaults = []
        return ast.arguments(
            posonlyargs=posonly_args,
            args=regular_args,
            vararg=ast.arg(arg=vararg) if vararg else None,
            kwonlyargs=kwonly_args,
            kw_defaults=[None] * len(kwonly_args),
            kwarg=ast.arg(arg=kwarg) if kwarg else None,
            defaults=defaults,
        )

    def _process_safe_jump(self, instr: Instruction) -> int:
        return 1

    #: Opcodes that must not appear inside the message of an ``assert``: they
    #: would make the message something other than a single expression.
    _ASSERT_MSG_UNSAFE = frozenset(
        ("YIELD_VALUE", "YIELD_FROM", "RETURN_VALUE", "RETURN_CONST", "POP_TOP",
         "SETUP_FINALLY", "SETUP_EXCEPT", "SETUP_WITH", "SETUP_ASYNC_WITH",
         "POP_BLOCK", "LOAD_ASSERTION_ERROR", "RAISE_VARARGS", "FOR_ITER",
         "GET_ITER", "END_ASYNC_FOR", "GET_AWAITABLE", "GET_ANEXT",
         "BEFORE_ASYNC_WITH", "PRINT_EXPR", "IMPORT_STAR")
    ) | frozenset(_STORE_OPS)

    def _try_emit_assert(
        self,
        instr: Instruction,
        instructions: List[Instruction],
        idx: int,
        code,
        stack: List[ast.expr],
        stmts: List[ast.stmt],
        limit: Optional[int] = None,
    ) -> int:
        """Rebuild ``assert test, msg`` out of the raise the compiler emits.

        ``assert`` has no opcode of its own.  The condition is compiled to a
        jump over an ``AssertionError`` that gets raised when it is false::

            <test>
            POP_JUMP_IF_TRUE <ok>
            LOAD_ASSERTION_ERROR
            <msg>
            RAISE_VARARGS 1
            <ok>:

        Read literally that is ``if not test: raise msg``, a statement that
        raises a *string* and so dies with ``TypeError: exceptions must derive
        from BaseException`` at exactly the moment the assertion is supposed to
        report something.  Returns the number of instructions consumed, or 0
        when this is an ordinary conditional jump.
        """
        if instr.opname != "POP_JUMP_IF_TRUE" or not stack:
            return 0
        limit_idx = len(instructions) if limit is None else limit
        if idx + 1 >= limit_idx or instructions[idx + 1].opname != "LOAD_ASSERTION_ERROR":
            return 0

        ok_offset = int(instr.argval) if instr.argval is not None else None
        if ok_offset is None:
            return 0

        # Locate the raise that closes the assert, and refuse the shape unless
        # everything in between can only build one expression.
        raise_at = -1
        for j in range(idx + 2, limit_idx):
            op = instructions[j]
            if op.opname == "RAISE_VARARGS":
                raise_at = j
                break
            if op.offset >= ok_offset or op.is_jump_target \
                    or op.opname in self._ASSERT_MSG_UNSAFE:
                return 0
        if raise_at < 0:
            return 0

        test = stack.pop()
        # The raise is an ``AssertionError(<msg>)`` call, and the two supported
        # layouts spell it differently: 3.9 loads the class, evaluates the
        # message and calls it with one argument, while 3.11+ evaluates the
        # message and then calls it with *no* arguments, taking the class from
        # the slot underneath.  Peel that closing call off in both shapes, or
        # the message comes out as ``msg()``.
        closing = instructions[raise_at - 1] if raise_at - 1 > idx + 1 else None
        body_end = raise_at
        if closing is not None and closing.opname in (
            "CALL_FUNCTION", "CALL", "CALL_KW", "CALL_FUNCTION_KW",
        ) and not (closing.arg or 0):
            body_end = raise_at - 1
        placeholder = ASTNode.make_Name("AssertionError", ast.Load())
        scratch: List[ast.expr] = [placeholder]
        scratch_stmts: List[ast.stmt] = []
        j = idx + 2
        while j < body_end:
            consumed = self._process_instruction(
                instructions[j], instructions, j, code, scratch, scratch_stmts,
                is_module=False, limit=body_end,
            )
            j += max(1, consumed or 1)
        msg = self._unwrap_assert_msg(scratch, placeholder)
        if msg is _NOT_AN_ASSERT or scratch_stmts:
            # The "message" turned out to be a statement run; keep the original
            # shape rather than invent an assert around it.
            scratch_stmts.extend(stmts)
            stmts[:] = scratch_stmts
            stack.append(test)
            return 0
        stmts.append(ast.Assert(test=test, msg=msg))
        return raise_at - idx + 1

    @staticmethod
    def _unwrap_assert_msg(scratch: List[ast.expr], placeholder: ast.expr):
        """Take the message off an ``assert`` scratch stack.

        Returns the value the raise would have wrapped in ``AssertionError(...)``,
        or ``None`` for a bare ``assert``.  Anything left over that does not fit
        either layout means the shape was not an ``assert`` after all, which is
        reported with :data:`_NOT_AN_ASSERT` so the caller can back out.
        """
        for k in range(len(scratch) - 1, -1, -1):
            node = scratch[k]
            if isinstance(node, ast.Call) and node.func is placeholder:
                # 3.9: ``AssertionError(<msg>)``.
                if len(node.args) != 1 or node.keywords:
                    break
                del scratch[k:]
                return node.args[0]
            if node is placeholder:
                # 3.9 with the closing call already peeled off.  Nothing above
                # the class is a bare ``assert``.
                above = scratch[k + 1:]
                if len(above) > 1:
                    break
                del scratch[k:]
                return above[0] if above else None
        else:
            # 3.11+ shape: no placeholder survives, the message is what is left.
            if len(scratch) == 1:
                return scratch[0]
            if not scratch:
                return None
        return _NOT_AN_ASSERT

    def _process_jump(
        self,
        instr: Instruction,
        instructions: List[Instruction],
        idx: int,
        code,
        stack: List[ast.expr],
        stmts: List[ast.stmt],
        limit: Optional[int] = None,
    ) -> int:
        opname = instr.opname
        # Disassembler._get_argval returns the *absolute* target offset for every
        # jump-family opcode (JUMP_FORWARD / JUMP_ABSOLUTE / POP_JUMP_IF_* / FOR_ITER).
        target = int(instr.argval if instr.argval is not None else (instr.arg or 0))
        if opname in ("JUMP_FORWARD", "JUMP_ABSOLUTE"):
            return self._handle_plain_jump(instr, instructions, idx, code, stack, stmts, target, limit)
        if opname in ("POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE"):
            if not stack:
                return 1
            cond = stack.pop()
            if opname == "POP_JUMP_IF_TRUE":
                cond = ast.UnaryOp(op=ast.Not(), operand=cond)
            return self._emit_conditional(cond, instructions, idx, code, stack, stmts, target)
        return 1

    def _handle_plain_jump(
        self,
        instr: Instruction,
        instructions: List[Instruction],
        idx: int,
        code,
        stack: List[ast.expr],
        stmts: List[ast.stmt],
        target: int,
        limit: Optional[int],
    ) -> int:
        """Handle JUMP_ABSOLUTE / JUMP_FORWARD.

        Inside a loop body these encode ``continue`` (jump back to the loop head)
        and ``break`` (jump past the loop exit).  At statement level a backward
        jump to the head of an enclosing range marks the end of a ``while True``.
        """
        kind = self._match_loop_jump(target)
        if kind == "continue":
            stmts.append(ast.Continue())
            return 1
        if kind == "break":
            stmts.append(ast.Break())
            return 1
        if target < instr.offset:
            head_idx = self._find_target_idx(instructions, target)
            return self._emit_while_true(instr, instructions, idx, code, stack, stmts, head_idx, limit)
        return 1

    def _emit_while_true(
        self,
        instr: Instruction,
        instructions: List[Instruction],
        idx: int,
        code,
        stack: List[ast.expr],
        stmts: List[ast.stmt],
        head_idx: int,
        limit: Optional[int],
    ) -> int:
        """Rebuild ``while True:`` from a backward JUMP_ABSOLUTE at the end of the body."""
        loop_end = self._compute_loop_end(instructions, head_idx, idx)
        exit_offset = (
            instructions[loop_end].offset
            if loop_end < len(instructions)
            else instructions[-1].offset + 2
        )
        body_stmts = self._emit_loop_body(
            code, instructions, head_idx, idx, instructions[head_idx].offset,
            exit_offset, jump_target=_jump_target(instr),
        )
        stmts.append(ast.While(test=ast.Constant(value=True), body=body_stmts, orelse=[]))
        return loop_end - head_idx

    def _find_while_cond(
        self, instructions: List[Instruction], start: int, end: int
    ) -> Optional[Tuple[int, int, int]]:
        """Detect ``while cond:`` whose head is the instruction at ``start``.

        Returns ``(cond_jump_idx, back_edge_idx, loop_end_idx)`` or ``None``.
        The head is a condition when the instructions following it are all
        expression-building opcodes terminated by a ``POP_JUMP_IF_*``; the loop
        is only a loop when a backward jump returns to the head from the body.
        """
        if start >= end or start >= len(instructions):
            return None
        head = instructions[start]
        if head.opname in ("FOR_ITER", "GET_ITER", "POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE"):
            return None
        if head.offset in self._loop_heads:
            return None
        j = start
        while j < end:
            op = instructions[j].opname
            if op in ("POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE"):
                break
            if op not in self._COND_EXPR_OPS:
                return None
            j += 1
        if j >= end:
            return None
        target = int(instructions[j].argval if instructions[j].argval is not None else 0)
        exit_idx = self._find_target_idx(instructions, target)
        head_offset = head.offset
        back_edge = None
        if exit_idx > j:
            for k in range(j + 1, exit_idx):
                ins = instructions[k]
                if ins.opname in ("JUMP_ABSOLUTE", "JUMP_FORWARD"):
                    jt = int(ins.argval if ins.argval is not None else 0)
                    if jt == head_offset:
                        back_edge = k
        elif instructions[exit_idx].opname in ("FOR_ITER", "GET_ITER"):
            # The condition's false branch leaves the loop *backwards*: CPython
            # aims it at the enclosing for loop's iterator, so ending this loop
            # continues the outer one.  A ``while`` nested directly in a ``for``
            # compiles to this shape, and there is no forward exit target to
            # bound the body with.
            for k in range(j + 1, len(instructions)):
                ins = instructions[k]
                if ins.opname in ("FOR_ITER", "GET_ITER"):
                    break  # another loop sits in between: not the plain shape
                if ins.opname in ("JUMP_ABSOLUTE", "JUMP_FORWARD"):
                    jt = int(ins.argval if ins.argval is not None else 0)
                    if jt == head_offset:
                        back_edge = k
                        break
                    if jt < ins.offset:
                        break  # some other loop's back edge: the body ends here
        if back_edge is None:
            return None
        return j, back_edge, self._compute_loop_end(instructions, start, back_edge)

    def _emit_while_cond(
        self,
        code,
        instructions: List[Instruction],
        start: int,
        end: int,
        cond_jump: int,
        back_edge: int,
        loop_end: int,
        stmts: List[ast.stmt],
    ) -> None:
        """Build ``while cond:`` from a head offset through its back edge."""
        head_offset = instructions[start].offset
        exit_offset = (
            instructions[loop_end].offset
            if loop_end < len(instructions)
            else instructions[-1].offset + 2
        )
        cond_stack: List[ast.expr] = []
        self._loop_heads.add(head_offset)
        try:
            self._emit_statements(
                code, instructions, is_module=False, start=start, end=cond_jump,
                out_stack=cond_stack,
            )
        finally:
            self._loop_heads.discard(head_offset)
        if not cond_stack:
            return
        cond = cond_stack[-1]
        # 3.12's inverted guard jumps *into* the body when the condition holds,
        # so the test is the condition as written rather than its negation.
        if instructions[cond_jump].opname == "POP_JUMP_IF_TRUE" \
                and not self._inverted_while_guard(instructions, cond_jump):
            cond = ast.UnaryOp(op=ast.Not(), operand=cond)
        # The body starts after the guard, or after the exit jump that follows
        # it when the guard is inverted.
        body_start = cond_jump + 2 if self._inverted_while_guard(
            instructions, cond_jump) else cond_jump + 1
        body_stmts = self._emit_loop_body(
            code, instructions, body_start, back_edge, head_offset, exit_offset,
        )
        # A backward exit -- the loop is nested in a ``for`` and its false
        # branch continues the outer loop -- has no ``else`` clause: the
        # target is the enclosing loop's iterator, not code behind this loop.
        # An inverted guard points at the body, which is not an exit either.
        orelse = []
        if not self._inverted_while_guard(instructions, cond_jump) \
                and self._jump_target(instructions[cond_jump]) >= head_offset:
            orelse = self._emit_while_else(
                code, instructions, cond_jump, exit_offset
            )
        stmts.append(
            ast.While(test=cond, body=body_stmts, orelse=orelse)
        )

    def _inverted_while_guard(self, instructions, cond_jump: int) -> bool:
        """Is the guard the 3.12 form, which jumps into the body?

        3.12 guards a ``while`` with ``POP_JUMP_IF_TRUE`` aimed at the body and
        puts the loop's exit in the unconditional jump right behind it, where
        earlier versions guard with ``POP_JUMP_IF_FALSE`` and jump forward to
        the exit.
        """
        guard = instructions[cond_jump]
        if guard.opname != "POP_JUMP_IF_TRUE":
            return False
        if cond_jump + 2 >= len(instructions):
            return False
        return (self._jump_target(guard) == instructions[cond_jump + 2].offset
                and instructions[cond_jump + 1].opname in (
                    "JUMP_ABSOLUTE", "JUMP_FORWARD", "JUMP_BACKWARD",
                    "JUMP_BACKWARD_NO_INTERRUPT"))

    def _emit_while_else(
        self,
        code,
        instructions: List[Instruction],
        cond_jump: int,
        exit_offset: int,
    ) -> List[ast.stmt]:
        """Build the ``else:`` clause of a ``while`` loop.

        The clause runs when the condition fails, so it starts at the condition
        jump's target.  A ``break`` leaves the loop past the clause, so the
        clause is only distinguishable from plain trailing code when the loop
        has one and the two targets differ.
        """
        target = self._jump_target(instructions[cond_jump])
        if target >= exit_offset:
            return []
        start = self._find_target_idx(instructions, target)
        stop = self._find_target_idx(instructions, exit_offset)
        if start >= stop or stop > len(instructions):
            return []
        return self._emit_statements(
            code, instructions, is_module=False, start=start, end=stop
        )

    def _find_while_true_back_edge(
        self, instructions: List[Instruction], start: int, end: int
    ) -> Optional[int]:
        """Last backward jump to the head of [start, end) -- the ``while True`` back edge."""
        if start >= end or start >= len(instructions):
            return None
        if instructions[start].opname == "FOR_ITER":
            return None
        head_offset = instructions[start].offset
        if head_offset in self._loop_heads:
            return None
        found = None
        for j in range(start, end):
            ins = instructions[j]
            if ins.opname in ("JUMP_ABSOLUTE", "JUMP_FORWARD"):
                jt = int(ins.argval if ins.argval is not None else (ins.arg or 0))
                if jt == head_offset:
                    found = j
        return found

    def _compute_loop_end(
        self, instructions: List[Instruction], start: int, back_edge: int
    ) -> int:
        """The loop runs up to the furthest forward jump out of its body (a `break`)."""
        loop_end = back_edge + 1
        for j in range(start, back_edge):
            ins = instructions[j]
            if ins.opname in ("JUMP_ABSOLUTE", "JUMP_FORWARD"):
                jt = int(ins.argval if ins.argval is not None else (ins.arg or 0))
                if jt > ins.offset:
                    loop_end = max(loop_end, self._find_target_idx(instructions, jt))
        return loop_end

    def _emit_loop_body(
        self,
        code,
        instructions: List[Instruction],
        start: int,
        end: int,
        head_offset: int,
        exit_offset: int,
        jump_target: Optional[int] = None,
    ) -> List[ast.stmt]:
        # ``head_offset`` is where the body starts; ``jump_target`` is the
        # offset a ``continue`` actually aims at, which is not always the same
        # thing.  A ``while True`` whose head sits just past a dropped ``NOP``
        # has its back edge aimed at the gap before it, and matching the two is
        # what stops the back edge from being read as a fresh loop head.
        self._loop_stack.append(
            (jump_target if jump_target is not None else head_offset, exit_offset)
        )
        # A `continue` inside the body is indistinguishable from the back edge, so
        # suppress ``while True`` detection for this range.
        self._loop_heads.add(head_offset)
        body_stack: List[ast.expr] = []
        try:
            body_stmts = self._emit_statements(
                code, instructions, is_module=False, start=start, end=end,
                out_stack=body_stack,
            )
        finally:
            self._loop_stack.pop()
            self._loop_heads.discard(head_offset)
        return body_stmts or [ast.Pass()]

    @staticmethod
    def _is_loop_exit_pop(instructions: List[Instruction], idx: int) -> bool:
        """True when the ``POP_TOP`` at *idx* only drops a loop's iterator.

        Leaving a loop body through ``return`` compiles to one
        ``ROT_TWO`` + ``POP_TOP`` pair per enclosing loop, so a ``return``
        inside nested loops repeats it, all of it immediately before the
        ``RETURN_VALUE``.  The value underneath must survive every one of them.
        """
        rotations = 0
        j = idx
        while (
            j >= 1
            and instructions[j - 1].opname == "ROT_TWO"
            and instructions[j].opname == "POP_TOP"
        ):
            rotations += 1
            j -= 2
        if not rotations:
            return False
        # Everything between the first rotation and the return has to belong to
        # the same teardown, otherwise this pop is an ordinary one.  A ``POP_BLOCK``
        # in between belongs to an enclosing ``try``/``finally`` and is still part
        # of the same unwinding.
        k = idx + 1
        while k < len(instructions) and instructions[k].opname in (
            "ROT_TWO", "ROT_THREE", "ROT_FOUR", "POP_TOP", "POP_BLOCK"
        ):
            k += 1
        return k < len(instructions) and instructions[k].opname == "RETURN_VALUE"

    @staticmethod
    def _return_value_after_pop_block(
        instructions: List[Instruction], pop_block_idx: int
    ) -> Optional[int]:
        """Index of the ``RETURN_VALUE`` of a return that follows the block pop.

        The compiler sometimes loads the value of a ``return`` *after* the
        ``POP_BLOCK`` that closes the protected range: a constant needs no
        work, so it is pushed afterwards.  Such a return belongs to the body
        even though its instructions sit outside the range the reader read.
        """
        j = pop_block_idx + 1
        n = len(instructions)
        if j >= n or instructions[j].opname not in (
            "LOAD_CONST", "LOAD_FAST", "LOAD_NAME", "LOAD_GLOBAL",
            "LOAD_DEREF", "LOAD_CLASSDEREF", "LOAD_CLOSURE",
        ):
            return None
        j += 1
        if j + 1 < n and instructions[j].opname in (
            "ROT_TWO", "ROT_THREE", "ROT_FOUR",
        ) and instructions[j + 1].opname == "POP_TOP":
            j += 2
        if j < n and instructions[j].opname == "RETURN_VALUE":
            return j
        return None

    @staticmethod
    def _is_return_after_pop_block(
        instructions: List[Instruction], pop_block_idx: int
    ) -> bool:
        """True when a ``RETURN_VALUE`` follows *pop_block_idx*, skipping loop
        teardown pairs (``ROT_TWO``/``POP_TOP``) that sit between them.

        When a ``return`` sits inside a ``try`` body that is itself inside a
        loop, the compiler emits one ``ROT_TWO`` + ``POP_TOP`` pair per
        enclosing loop before the ``RETURN_VALUE``.  The value to return is
        still on the virtual stack when the try-body range ends, so we must
        recognise the pattern even when those teardown pairs intervene.
        """
        j = pop_block_idx + 1
        while (
            j + 1 < len(instructions)
            and instructions[j].opname in ("ROT_TWO", "ROT_THREE", "ROT_FOUR", "POP_BLOCK")
            and instructions[j + 1].opname == "POP_TOP"
        ):
            j += 2
        return j < len(instructions) and instructions[j].opname == "RETURN_VALUE"

    _IFEXP_EXPR_OPS = {
        "LOAD_CONST", "LOAD_NAME", "LOAD_FAST", "LOAD_GLOBAL", "LOAD_DEREF",
        "LOAD_CLOSURE", "LOAD_CLASSDEREF", "LOAD_ATTR", "LOAD_METHOD",
        "BINARY_ADD", "BINARY_SUBTRACT", "BINARY_MULTIPLY", "BINARY_MATRIX_MULTIPLY",
        "BINARY_TRUE_DIVIDE", "BINARY_FLOOR_DIVIDE", "BINARY_MODULO", "BINARY_POWER",
        "BINARY_LSHIFT", "BINARY_RSHIFT", "BINARY_AND", "BINARY_OR", "BINARY_XOR",
        "UNARY_NEGATIVE", "UNARY_POSITIVE", "UNARY_NOT", "UNARY_INVERT",
        "COMPARE_OP", "IS_OP", "CONTAINS_OP", "BINARY_SUBSCR",
        "CALL_FUNCTION", "CALL_FUNCTION_KW", "CALL_FUNCTION_EX", "CALL_METHOD",
        "CALL_METHOD_KW", "CALL_KW", "BUILD_TUPLE", "BUILD_LIST", "BUILD_SET",
        "BUILD_STRING", "BUILD_CONST_KEY_MAP", "BUILD_MAP", "BUILD_SLICE",
        "FORMAT_VALUE", "LIST_EXTEND", "SET_UPDATE", "DICT_UPDATE", "DICT_MERGE",
        "KW_NAMES", "DUP_TOP", "DUP_TOP_TWO", "ROT_TWO", "ROT_THREE", "ROT_FOUR", "ROT_N",
        "NOP",
    }
    _IFEXP_MAX_DEPTH = 16
    _IFEXP_STORE_OPS = {
        "STORE_FAST", "STORE_NAME", "STORE_GLOBAL", "STORE_DEREF",
    }
    # Opcodes that may immediately follow a conditional expression whose value
    # is consumed as an operand rather than stored, e.g. ``a + (b if c else d)``.
    _IFEXP_CONT_OPS = {
        "BINARY_ADD", "BINARY_SUBTRACT", "BINARY_MULTIPLY", "BINARY_MATRIX_MULTIPLY",
        "BINARY_TRUE_DIVIDE", "BINARY_FLOOR_DIVIDE", "BINARY_MODULO", "BINARY_POWER",
        "BINARY_LSHIFT", "BINARY_RSHIFT", "BINARY_AND", "BINARY_OR", "BINARY_XOR",
        "COMPARE_OP", "IS_OP", "CONTAINS_OP", "BINARY_SUBSCR",
        "CALL_FUNCTION", "CALL_FUNCTION_KW", "CALL_FUNCTION_EX", "CALL_METHOD",
        "CALL_METHOD_KW", "CALL_KW", "KW_NAMES",
        "INPLACE_ADD", "INPLACE_SUBTRACT", "INPLACE_MULTIPLY", "INPLACE_MATRIX_MULTIPLY",
        "INPLACE_TRUE_DIVIDE", "INPLACE_FLOOR_DIVIDE", "INPLACE_MODULO", "INPLACE_POWER",
        "INPLACE_LSHIFT", "INPLACE_RSHIFT", "INPLACE_AND", "INPLACE_XOR", "INPLACE_OR",
        "YIELD_VALUE",
    }
    # Short-circuit guards.  A value-position ``and``/``or`` always ends in a
    # ``JUMP_IF_*_OR_POP``; the leading ``POP_JUMP_IF_*`` of a left-associative
    # ``a and b ... or c`` are the only place where a pop-jump guards a value.
    _VALUE_GUARD_OPS = {
        "JUMP_IF_FALSE_OR_POP", "JUMP_IF_TRUE_OR_POP",
        "POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE",
    }
    _VALUE_OR_POP_OPS = ("JUMP_IF_FALSE_OR_POP", "JUMP_IF_TRUE_OR_POP")

    def _jump_target(self, instr: Instruction) -> int:
        return int(instr.argval if instr.argval is not None else (instr.arg or 0))

    def _compare_op(self, instr: Instruction) -> ast.cmpop:
        name = instr.argval
        return COMPARE_OPS.get(name if isinstance(name, str) else "==", ast.Eq)()

    #: Opcodes that can act as one link of a chained comparison.  ``IS_OP`` and
    #: ``CONTAINS_OP`` are separate opcodes that carry their negation in the
    #: argument rather than in the opcode name.
    _CHAIN_CMP_OPS = ("COMPARE_OP", "IS_OP", "CONTAINS_OP")

    def _chain_compare_op(self, instr: Instruction) -> ast.cmpop:
        if instr.opname == "COMPARE_OP":
            return self._compare_op(instr)
        negate = bool(instr.arg)
        if instr.opname == "IS_OP":
            return ast.IsNot() if negate else ast.Is()
        return ast.NotIn() if negate else ast.In()

    def _is_chain_link(self, instructions: List[Instruction], i: int, end: int) -> bool:
        """True when ``i`` starts a ``DUP_TOP``/``ROT_THREE``/<compare> triple."""
        return (
            i + 2 < end
            and instructions[i].opname == "DUP_TOP"
            and instructions[i + 1].opname == "ROT_THREE"
            and instructions[i + 2].opname in self._CHAIN_CMP_OPS
        )

    def _find_value_chain_marker(
        self, instructions: List[Instruction], start: int, end: int
    ) -> Optional[int]:
        """Locate the first ``DUP_TOP`` of a value-position chained comparison."""
        for j in range(start, end):
            if self._is_chain_link(instructions, j, end):
                return j
            if instructions[j].opname not in self._IFEXP_EXPR_OPS:
                return None
        return None

    def _find_chain_marker(self, instructions: List[Instruction], start: int, end: int) -> Optional[int]:
        """Locate the ``DUP_TOP``/``ROT_THREE``/``COMPARE_OP`` triple of a chained comparison.

        ``a < b < c`` duplicates the middle operand so each link can be guarded
        separately, which is the only trace a chained comparison leaves in the
        instruction stream.
        """
        for j in range(start, end):
            op = instructions[j].opname
            if (
                op == "DUP_TOP"
                and j + 2 < end
                and instructions[j + 1].opname == "ROT_THREE"
                and instructions[j + 2].opname == "COMPARE_OP"
            ):
                return j
            if op not in self._IFEXP_EXPR_OPS:
                return None
        return None

    def _parse_chained_term(
        self,
        code,
        instructions: List[Instruction],
        start: int,
        marker: int,
        end: int,
        stack: List[ast.expr],
    ) -> Optional[Tuple[ast.expr, int, int]]:
        """Parse ``a op b op c [op d ...]`` guarded by one jump per link.

        Every link but the last duplicates the operand it shares with the next
        one, so a chain of any length is the same shape repeated: the
        ``DUP_TOP``/``ROT_THREE``/``COMPARE_OP`` marker, a guard to the shared
        epilogue, then the next operand.  Only the last link compares its
        operand directly, and its guard decides whether the whole chain holds.

        Returns ``(expr, guard_idx, merge_offset)`` where ``guard_idx`` is the
        jump that decides whether the whole chain holds.
        """
        vals = self._eval_ifexp_expr(code, instructions, start, marker, stack)
        if vals is None or len(vals) != len(stack) + 2:
            return None
        left, mid = vals[-2], vals[-1]
        first_guard = marker + 3
        if first_guard >= end or instructions[first_guard].opname not in (
            "POP_JUMP_IF_FALSE",
            "POP_JUMP_IF_TRUE",
        ):
            return None
        ops: List[ast.cmpop] = [self._compare_op(instructions[marker + 2])]
        comparators: List[ast.expr] = [mid]
        # The middle operand stays on the stack for the next link to reuse.
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
            # The right operand is evaluated on top of the duplicated value.
            rhs = self._eval_ifexp_expr(code, instructions, i, j, cur)
            if rhs is None or len(rhs) != len(cur) + 1:
                return None
            if link is None:
                compare, guard = j, j + 1
            else:
                compare, guard = j + 2, j + 3
            if guard >= end or instructions[guard].opname not in (
                "POP_JUMP_IF_FALSE",
                "POP_JUMP_IF_TRUE",
            ):
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
        # Every failing link but the last jumps to a POP_TOP epilogue that then
        # jumps to the same merge point; confirm that so a plain ``a < b`` is
        # never mistaken for a chain.
        for link_guard in link_guards[:-1]:
            epilogue = self._find_target_idx(instructions, self._jump_target(instructions[link_guard]))
            if epilogue < guard + 1 or epilogue + 1 >= end:
                return None
            if instructions[epilogue].opname != "POP_TOP":
                return None
            if self._jump_target(instructions[epilogue + 1]) != merge:
                return None
        return expr, guard, merge

    def _parse_cond_term(
        self,
        code,
        instructions: List[Instruction],
        start: int,
        end: int,
        stack: List[ast.expr],
    ) -> Optional[Tuple[ast.expr, int, int, int, bool]]:
        """Parse one comparison term of a short-circuit condition."""
        marker = self._find_chain_marker(instructions, start, end)
        if marker is not None:
            chained = self._parse_chained_term(code, instructions, start, marker, end, stack)
            if chained is None:
                return None
            expr, guard, merge = chained
            return expr, guard, merge, guard + 1, True
        guard = self._find_ifexp_condition_jump(instructions, start, end)
        if guard is None:
            return None
        vals = self._eval_ifexp_expr(code, instructions, start, guard, stack)
        if not self._is_ifexp_value_stack(vals, stack):
            return None
        expr = vals[-1]
        if instructions[guard].opname == "POP_JUMP_IF_TRUE":
            expr = ast.UnaryOp(op=ast.Not(), operand=expr)
        return expr, guard, self._jump_target(instructions[guard]), guard + 1, False

    def _parse_cond_chain(
        self,
        code,
        instructions: List[Instruction],
        idx: int,
        end: int,
        stack: List[ast.expr],
    ) -> Optional[Tuple[ast.expr, int, int, int, List[Tuple[int, int]]]]:
        """Parse ``t1 and t2 and ...`` where each term is a comparison.

        Every term must jump to the same merge offset; that shared target is
        what makes the sequence a single ``and`` rather than nested ``if``\\s.
        """
        terms: List[ast.expr] = []
        merge: Optional[int] = None
        guard_idx: Optional[int] = None
        next_idx = idx
        any_chained = False
        handled: List[Tuple[int, int]] = []
        i = idx
        while i < end:
            parsed = self._parse_cond_term(code, instructions, i, end, stack)
            if parsed is None:
                if not terms:
                    return None
                # A chained term jumps over its cleanup into whatever follows
                # the condition.  That may be another operand of the same
                # ``and``, or -- when the chain is the whole test -- the branch
                # body, which ends the condition right here.
                break
            expr, term_guard, term_merge, term_next, chained = parsed
            if merge is None:
                merge = term_merge
            elif term_merge != merge:
                return None
            terms.append(expr)
            any_chained = any_chained or chained
            guard_idx = term_guard
            next_idx = term_next
            if term_next < end and instructions[term_next].opname == "JUMP_FORWARD":
                target = self._find_target_idx(instructions, self._jump_target(instructions[term_next]))
                if target <= term_next or target >= end:
                    return None
                handled.append((term_next, target))
                i = target
                continue
            break
        if guard_idx is None or merge is None:
            return None
        if len(terms) < 2 and not any_chained:
            return None
        if len(terms) == 1:
            expr = terms[0]
        else:
            expr = ast.BoolOp(op=ast.And(), values=terms)
        return expr, guard_idx, merge, next_idx, handled

    def _try_emit_chain_cond(
        self,
        code,
        instructions: List[Instruction],
        idx: int,
        end: int,
        stack: List[ast.expr],
        stmts: List[ast.stmt],
    ) -> int:
        """Rebuild a condition built from chained comparisons joined by ``and``."""
        parsed = self._parse_cond_chain(code, instructions, idx, end, stack)
        if parsed is None:
            return 0
        cond, guard_idx, merge, next_idx, handled = parsed
        self._handled_ranges.extend(handled)
        consumed = self._emit_conditional(cond, instructions, guard_idx, code, stack, stmts, merge)
        # ``consumed`` is measured from ``guard_idx``; the condition itself spans
        # from ``idx`` up to whichever of the two reaches further.
        return max(next_idx, guard_idx + consumed) - idx

    def _try_emit_boolop(
        self,
        code,
        instructions: List[Instruction],
        idx: int,
        end: int,
        stack: List[ast.expr],
        stmts: List[ast.stmt],
    ) -> int:
        """Try to rebuild a short-circuit ``and``/``or`` condition.

        Every operand of a short-circuit chain is guarded by a
        ``POP_JUMP_IF_*``.  Only the operands before the last one can leave the
        chain early, and each of them jumps either into the body or past it;
        the last guard always targets the merge point, and the body begins on
        the instruction right after it.  Polarity together with that choice of
        target names the operator uniquely: guards that all skip the body build
        an ``and`` (of negated operands when they test for truth), while guards
        that all enter the body build an ``or``.
        """
        if idx >= end or idx >= len(instructions):
            return 0
        operands: List[ast.expr] = []
        guards: List[int] = []
        i = idx
        while i < end:
            guard = self._find_ifexp_condition_jump(instructions, i, end)
            if guard is None:
                break
            vals = self._eval_ifexp_expr(code, instructions, i, guard, stack)
            if not self._is_ifexp_value_stack(vals, stack):
                return 0
            operands.append(vals[-1])
            guards.append(guard)
            i = guard + 1
        if len(guards) < 2:
            return 0
        last = guards[-1]
        merge = self._jump_target(instructions[last])
        merge_idx = self._find_target_idx(instructions, merge)
        if merge_idx <= last or merge_idx > end:
            return 0
        body_offset = instructions[last + 1].offset
        # Every guard but the last must land either in the body or at the merge;
        # anything else means the operands are really separate statements.
        enters_body: List[bool] = []
        for guard in guards[:-1]:
            target = self._jump_target(instructions[guard])
            if target == merge:
                enters_body.append(False)
            elif target == body_offset:
                enters_body.append(True)
            else:
                return 0
        opnames = [instructions[g].opname for g in guards]
        leading = opnames[:-1]
        if not any(enters_body):
            if all(op == "POP_JUMP_IF_FALSE" for op in opnames):
                cond = ast.BoolOp(op=ast.And(), values=operands)
            elif all(op == "POP_JUMP_IF_TRUE" for op in opnames):
                cond = ast.UnaryOp(
                    op=ast.Not(),
                    operand=ast.BoolOp(op=ast.Or(), values=operands),
                )
            else:
                return 0
        elif all(enters_body):
            if (
                all(op == "POP_JUMP_IF_TRUE" for op in leading)
                and opnames[-1] == "POP_JUMP_IF_FALSE"
            ):
                cond = ast.BoolOp(op=ast.Or(), values=operands)
            elif (
                all(op == "POP_JUMP_IF_FALSE" for op in leading)
                and opnames[-1] == "POP_JUMP_IF_TRUE"
            ):
                cond = ast.UnaryOp(
                    op=ast.Not(),
                    operand=ast.BoolOp(op=ast.And(), values=operands),
                )
            else:
                return 0
        else:
            return 0
        consumed = self._emit_conditional(
            cond, instructions, last, code, stack, stmts, merge
        )
        return consumed + (last - idx)

    def _make_boolop(self, op: ast.boolop, left: ast.expr, right: ast.expr) -> ast.BoolOp:
        """Join two operands with ``op``, flattening chains of the same operator."""
        if isinstance(left, ast.BoolOp) and type(left.op) is type(op):
            return ast.BoolOp(op=op, values=list(left.values) + [right])
        return ast.BoolOp(op=op, values=[left, right])

    def _find_value_guard(
        self, instructions: List[Instruction], start: int, end: int
    ) -> Optional[int]:
        """Locate the next short-circuit guard inside a value expression."""
        for j in range(start, end):
            op = instructions[j].opname
            if op in self._VALUE_GUARD_OPS:
                return j if j > start else None
            if op not in self._IFEXP_EXPR_OPS:
                return None
        return None

    def _parse_value_boolop_run(
        self,
        code,
        instructions: List[Instruction],
        idx: int,
        end: int,
        base: List[ast.expr],
        left: ast.expr,
    ) -> Optional[Tuple[List[ast.expr], int]]:
        """Extend ``left`` with the short-circuit operand guarded at ``idx``.

        ``left`` is already evaluated and pushed on the stack -- typically a
        chained comparison whose cleanup has just run -- so only the operand
        still missing is parsed here.  A leading run of ``POP_JUMP_IF_*``
        belongs to the ``and`` part of a left-associative ``a and b and c or d``:
        each pops its condition and hands the failure to the same fallback, and
        the trailing ``JUMP_IF_*_OR_POP`` is the outer ``or``.  Requiring that
        trailing guard is what keeps nested ``if`` statements, whose guards are
        all pop-jumps, from being mistaken for a value expression.

        Returns ``(stack with the combined value on top, next_idx)``.
        """
        if idx >= end or idx >= len(instructions):
            return None
        if instructions[idx].opname not in self._VALUE_GUARD_OPS:
            return None

        g = idx
        fallback: Optional[int] = None
        while instructions[g].opname not in self._VALUE_OR_POP_OPS:
            opname = instructions[g].opname
            if opname not in ("POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE"):
                return None
            target = self._jump_target(instructions[g])
            if fallback is None:
                fallback = target
            elif fallback != target:
                return None
            nxt = self._find_value_guard(instructions, g + 1, end)
            if nxt is None:
                return None
            right = self._eval_value_operand(code, instructions, g + 1, nxt, base)
            if not self._is_ifexp_value_stack(right, base):
                return None
            op = ast.And() if opname == "POP_JUMP_IF_FALSE" else ast.Or()
            left = self._make_boolop(op, left, right[-1])
            g = nxt

        opname = instructions[g].opname
        op = ast.And() if opname == "JUMP_IF_FALSE_OR_POP" else ast.Or()
        target_idx = self._find_target_idx(instructions, self._jump_target(instructions[g]))
        if target_idx > end:
            return None
        # The operand is evaluated on the fall-through path; a nested
        # short-circuit makes that path empty, and the operand then starts at
        # the jump target and runs up to its own merge point.
        right = None
        if g + 1 < target_idx:
            right = self._eval_value_operand(code, instructions, g + 1, target_idx, base)
        if self._is_ifexp_value_stack(right, base):
            return list(base) + [self._make_boolop(op, left, right[-1])], target_idx
        nested = self._parse_value_boolop_at(code, instructions, target_idx, end, base)
        if nested is None:
            return None
        nested_stack, merge_idx = nested
        if merge_idx > end:
            return None
        return list(base) + [self._make_boolop(op, left, nested_stack[-1])], merge_idx

    def _parse_value_boolop_at(
        self,
        code,
        instructions: List[Instruction],
        idx: int,
        end: int,
        stack: List[ast.expr],
    ) -> Optional[Tuple[List[ast.expr], int]]:
        """Parse a self-contained value ``and``/``or`` starting at ``idx``."""
        if idx >= end or idx >= len(instructions):
            return None
        guard = self._find_value_guard(instructions, idx, end)
        if guard is None:
            return None
        left = self._eval_value_operand(code, instructions, idx, guard, stack)
        if not self._is_ifexp_value_stack(left, stack):
            return None
        return self._parse_value_boolop_run(code, instructions, guard, end, list(stack), left[-1])

    def _try_emit_value_boolop(
        self,
        code,
        instructions: List[Instruction],
        idx: int,
        end: int,
        stack: List[ast.expr],
    ) -> int:
        """Rebuild an ``and``/``or`` that produces a value.

        In value position CPython emits ``JUMP_IF_FALSE_OR_POP`` for ``and`` and
        ``JUMP_IF_TRUE_OR_POP`` for ``or``: the jump either keeps the left operand
        on the stack or pops it and evaluates the right one.  Both land on the
        same instruction, which consumes the result.  When a value is already on
        the stack -- the result of a chained comparison -- only the guard run is
        left to parse.
        """
        if idx >= end or idx >= len(instructions):
            return 0
        if stack and instructions[idx].opname in self._VALUE_OR_POP_OPS:
            parsed = self._parse_value_boolop_run(
                code, instructions, idx, end, list(stack[:-1]), stack[-1]
            )
        else:
            parsed = self._parse_value_boolop_at(code, instructions, idx, end, list(stack))
        if parsed is None:
            return 0
        result, next_idx = parsed
        stack[:] = result
        return next_idx - idx

    def _eval_value_operand(
        self,
        code,
        instructions: List[Instruction],
        start: int,
        end: int,
        stack: List[ast.expr],
    ) -> Optional[List[ast.expr]]:
        """Evaluate ``[start, end)`` as a single value.

        A right operand of a short-circuit expression is not necessarily
        straight-line code: it may itself be a chained comparison or another
        ``and``/``or``, and both need their own cleanup-aware parse.
        """
        if start >= end:
            return None
        marker = self._find_chain_marker(instructions, start, end)
        if marker is not None:
            chained = self._parse_value_chain(
                code, instructions, start, marker, end, stack
            )
            if chained is not None:
                return chained[0]
        parsed = self._parse_value_boolop_at(code, instructions, start, end, list(stack))
        if parsed is not None:
            return parsed[0]
        return self._eval_ifexp_expr(code, instructions, start, end, stack)

    def _find_value_chain_compare(
        self, instructions: List[Instruction], start: int, end: int
    ) -> Optional[int]:
        """Locate the ``COMPARE_OP`` of the next link of a value chain.

        Every link but the last duplicates the operand it has just evaluated
        so the link after it has a middle to compare with, which marks it as
        ``DUP_TOP``/``ROT_THREE``/``COMPARE_OP``; the last link compares
        against the retained value directly.
        """
        for j in range(start, end):
            op = instructions[j].opname
            if op == "COMPARE_OP":
                return j
            if (
                op == "DUP_TOP"
                and j + 2 < end
                and instructions[j + 1].opname == "ROT_THREE"
                and instructions[j + 2].opname == "COMPARE_OP"
            ):
                return j + 2
            if op not in self._IFEXP_EXPR_OPS:
                return None
        return None

    def _parse_value_chain(
        self,
        code,
        instructions: List[Instruction],
        start: int,
        marker: int,
        end: int,
        stack: List[ast.expr],
    ) -> Optional[Tuple[List[ast.expr], int]]:
        """Parse a chained comparison that produces a value.

        In value position every link but the last is guarded by
        ``JUMP_IF_*_OR_POP`` towards a shared ``ROT_TWO``/``POP_TOP`` cleanup,
        because a short-circuited chain must also drop the operand it kept for
        the following link.  The chain therefore does not end at its last
        guard: the result is consumed either by the instruction right after
        the cleanup or by a ``JUMP_FORWARD`` landing there, and in the final
        position of an expression not even that jump exists -- both paths then
        run the same consumer.

        Returns ``(stack with the result on top, next_idx)``.
        """
        vals = self._eval_ifexp_expr(code, instructions, start, marker, stack)
        if vals is None or len(vals) != len(stack) + 2:
            return None
        left, mid = vals[-2], vals[-1]
        ops = [self._compare_op(instructions[marker + 2])]
        comparators = [mid]
        i = marker + 3
        after = i
        cont_idx = i
        while True:
            if i >= end or instructions[i].opname not in (
                "JUMP_IF_FALSE_OR_POP",
                "JUMP_IF_TRUE_OR_POP",
            ):
                return None
            fail_offset = self._jump_target(instructions[i])
            fail_idx = self._find_target_idx(instructions, fail_offset)
            if not i < fail_idx or fail_idx + 1 >= len(instructions):
                return None
            if (
                instructions[fail_idx].opname != "ROT_TWO"
                or instructions[fail_idx + 1].opname != "POP_TOP"
            ):
                return None
            cont_idx = fail_idx + 2
            if cont_idx > end:
                return None
            nxt_cmp = self._find_value_chain_compare(instructions, i + 1, fail_idx)
            if nxt_cmp is None:
                return None
            # The retained operand of the previous link sits below the
            # operand evaluated for this one.
            rhs = self._eval_ifexp_expr(code, instructions, i + 1, nxt_cmp, [mid])
            if rhs is None or len(rhs) != 2:
                return None
            ops.append(self._compare_op(instructions[nxt_cmp]))
            comparators.append(rhs[-1])
            mid = rhs[-1]
            after = nxt_cmp + 1
            if (
                after < fail_idx
                and instructions[after].opname
                in ("JUMP_IF_FALSE_OR_POP", "JUMP_IF_TRUE_OR_POP")
                and self._jump_target(instructions[after]) == fail_offset
            ):
                i = after
                continue
            break
        if after < fail_idx:
            # Success jumps over the cleanup, or -- in final position -- runs
            # the same consumer the cleanup falls into.
            if instructions[after].opname == "JUMP_FORWARD":
                if self._find_target_idx(
                    instructions, self._jump_target(instructions[after])
                ) != cont_idx:
                    return None
            elif not (
                instructions[after].opname == "RETURN_VALUE"
                and instructions[cont_idx].opname == "RETURN_VALUE"
            ):
                return None
        elif after != cont_idx:
            return None
        return (
            list(stack) + [ast.Compare(left=left, ops=ops, comparators=comparators)],
            cont_idx,
        )

    def _find_value_chain_boundary(
        self, instructions: List[Instruction], start: int, end: int
    ) -> Optional[int]:
        """Index where the operand of the current chain link stops.

        Either a bare ``COMPARE_OP`` -- the chain's last link, which compares
        directly against the retained value -- or the ``DUP_TOP`` that starts
        the next link's ``DUP_TOP``/``ROT_THREE``/``COMPARE_OP`` triple.
        """
        for j in range(start, end):
            op = instructions[j].opname
            if op in self._CHAIN_CMP_OPS:
                return j
            if self._is_chain_link(instructions, j, end):
                return j
            if op not in self._IFEXP_EXPR_OPS:
                return None
        return None

    def _match_compare_chain(
        self,
        code,
        instructions: List[Instruction],
        start: int,
        marker: int,
        end: int,
        base: Optional[List[ast.expr]] = None,
    ) -> Optional[Tuple[ast.Compare, int]]:
        """Recognise a chained comparison in value position, any number of links.

        ``a < b < c < d`` compiles to one ``DUP_TOP``/``ROT_THREE``/
        ``COMPARE_OP``/``JUMP_IF_*_OR_POP`` group per link except the last,
        every guard aimed at one shared ``ROT_TWO``/``POP_TOP`` cleanup.  The
        repetition is uniform, so the chain is read off link by link and turned
        into a single :class:`ast.Compare` -- which matters because reading only
        the first two links turns ``a < b < c < d`` into ``((a < b) < c) < d``,
        a different expression with a different meaning.

        Returns ``(expr, consumer_idx)``, where ``consumer_idx`` is the
        instruction that takes the boolean result, or ``None`` when the shape
        does not match.
        """
        known = list(base or [])
        vals = self._eval_ifexp_expr(code, instructions, start, marker, known)
        # Exactly the values already on the stack plus the chain's two leading
        # operands.  Anything more means ``start`` is not the beginning of the
        # chain -- ``return r, not (a < b ...)`` reaches here with ``LOAD_GLOBAL
        # r`` still to be processed, and claiming it would drop ``r``.
        if vals is None or len(vals) != len(known) + 2:
            return None
        left = vals[-2]
        ops: List[ast.cmpop] = []
        comparators: List[ast.expr] = [vals[-1]]
        fail_offsets: List[int] = []

        i = marker
        while self._is_chain_link(instructions, i, end):
            guard_idx = i + 3
            if guard_idx >= end or instructions[guard_idx].opname not in (
                "JUMP_IF_FALSE_OR_POP",
                "JUMP_IF_TRUE_OR_POP",
            ):
                return None
            fail_offsets.append(self._jump_target(instructions[guard_idx]))
            ops.append(self._chain_compare_op(instructions[i + 2]))
            boundary = self._find_value_chain_boundary(instructions, i + 4, end)
            if boundary is None:
                return None
            operand = self._eval_ifexp_expr(code, instructions, i + 4, boundary, [])
            if not operand:
                return None
            comparators.append(operand[-1])
            i = boundary

        # The last link has no duplicate to keep, so it compares directly and
        # is not guarded -- the result just flows on to its consumer.
        if i >= end or instructions[i].opname not in self._CHAIN_CMP_OPS:
            return None
        ops.append(self._chain_compare_op(instructions[i]))
        if not fail_offsets:
            # ``a < b`` has no shared cleanup at all; not a chain.
            return None
        fail_idx = self._find_target_idx(instructions, fail_offsets[0])
        if fail_idx + 1 >= len(instructions):
            return None
        if (
            instructions[fail_idx].opname != "ROT_TWO"
            or instructions[fail_idx + 1].opname != "POP_TOP"
        ):
            return None
        if any(offset != fail_offsets[0] for offset in fail_offsets):
            return None
        # The short-circuiting path jumps past the cleanup; the successful path
        # falls straight through to the same consumer.  Pick whichever one the
        # bytecode actually runs, so the caller resumes in the right place.
        next_idx = i + 1
        if next_idx < end and instructions[next_idx].opname in (
            "JUMP_FORWARD", "JUMP_ABSOLUTE"
        ):
            landing = self._find_target_idx(
                instructions, self._jump_target(instructions[next_idx])
            )
            if landing != fail_idx + 2:
                return None
            next_idx = landing
        return ast.Compare(left=left, ops=ops, comparators=comparators), next_idx

    def _try_emit_value_chain(
        self,
        code,
        instructions: List[Instruction],
        idx: int,
        end: int,
        stack: List[ast.expr],
    ) -> int:
        marker = self._find_chain_marker(instructions, idx, end)
        if marker is None:
            marker = self._find_value_chain_marker(instructions, idx, end)
        if marker is None:
            return 0
        parsed = self._parse_value_chain(code, instructions, idx, marker, end, stack)
        if parsed is None:
            chained = self._match_compare_chain(
                code, instructions, idx, marker, end, stack
            )
            if chained is None:
                return 0
            expr, next_idx = chained
            stack.append(expr)
            if next_idx < end and instructions[next_idx].opname in self._VALUE_GUARD_OPS:
                run = self._parse_value_boolop_run(
                    code, instructions, next_idx, end, list(stack), expr
                )
                if run is not None:
                    stack[:], next_idx = run[0], run[1]
            return next_idx - idx
        result, next_idx = parsed
        # The chain result stays on the stack, so an enclosing ``and``/``or``
        # is spelled by the guards sitting right after the cleanup.
        if next_idx < end and instructions[next_idx].opname in self._VALUE_GUARD_OPS:
            run = self._parse_value_boolop_run(
                code, instructions, next_idx, end, list(stack), result[-1]
            )
            if run is not None:
                result, next_idx = run
        stack[:] = result
        return next_idx - idx

    def _try_emit_ifexp(
        self,
        code,
        instructions: List[Instruction],
        idx: int,
        end: int,
        stack: List[ast.expr],
        stmts: List[ast.stmt],
        allow_return: bool = False,
    ) -> int:
        """Try to rebuild a conditional expression beginning at ``idx``.

        CPython 3.9 emits a conditional expression as a guarded expression
        followed by either a common store or two independent returns.  This
        deliberately accepts only straight-line expression ranges; ordinary
        ``if`` statements containing stores, calls with side effects, or nested
        control flow continue through :meth:`_emit_conditional`.
        """
        if idx >= end or idx >= len(instructions):
            return 0
        if instructions[idx].opname in (
            "POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE", "JUMP_ABSOLUTE", "JUMP_FORWARD"
        ):
            return 0

        cond_jump = self._find_ifexp_condition_jump(instructions, idx, end)
        if cond_jump is None:
            return 0
        cond_instr = instructions[cond_jump]
        target = int(cond_instr.argval if cond_instr.argval is not None else (cond_instr.arg or 0))
        else_idx = self._find_target_idx(instructions, target)
        if else_idx <= cond_jump or else_idx >= end:
            return 0

        # Evaluate the condition on a copy of the incoming virtual stack.  The
        # real stack is updated only after the complete pattern is accepted.
        condition_stack = self._eval_ifexp_expr(
            code, instructions, idx, cond_jump, stack
        )
        # The range may also carry a partially built left operand (``a + (b if
        # c else d)`` pushes ``a`` before evaluating the guard), so more than
        # one value may be added; the guard is always the topmost one.
        if condition_stack is None or len(condition_stack) <= len(stack):
            return 0
        cond = condition_stack[-1]
        if cond_instr.opname == "POP_JUMP_IF_TRUE":
            cond = ast.UnaryOp(op=ast.Not(), operand=cond)
        branch_base = condition_stack[:-1]

        merge_jump = self._find_ifexp_merge_jump(instructions, cond_jump, else_idx, end)
        if merge_jump is not None:
            merge_jump_idx, merge_idx = merge_jump

            # Most conditional assignments have one STORE after both branches.
            if (
                merge_idx < end
                and instructions[merge_idx].opname in self._IFEXP_STORE_OPS
            ):
                then_stack = self._eval_ifexp_expr(
                    code, instructions, cond_jump + 1, merge_jump_idx, branch_base
                )
                else_stack = self._eval_ifexp_expr(
                    code, instructions, else_idx, merge_idx, branch_base
                )
                if self._is_ifexp_value_stack(then_stack, branch_base) and self._is_ifexp_value_stack(
                    else_stack, branch_base
                ):
                    value = ast.IfExp(
                        test=cond,
                        body=then_stack[-1],
                        orelse=else_stack[-1],
                    )
                    stack[:] = branch_base + [value]
                    return merge_idx - idx

            # An infix conditional expression merges into a binary/call operator
            # rather than a store; the IfExp is pushed back for that operator.
            if (
                merge_idx < end
                and instructions[merge_idx].opname in self._IFEXP_CONT_OPS
            ):
                then_stack = self._eval_ifexp_expr(
                    code, instructions, cond_jump + 1, merge_jump_idx, branch_base
                )
                else_stack = self._eval_ifexp_expr(
                    code, instructions, else_idx, merge_idx, branch_base
                )
                if self._is_ifexp_value_stack(then_stack, branch_base) and self._is_ifexp_value_stack(
                    else_stack, branch_base
                ):
                    value = ast.IfExp(
                        test=cond,
                        body=then_stack[-1],
                        orelse=else_stack[-1],
                    )
                    stack[:] = branch_base + [value]
                    return merge_idx - idx

        # NOTE: an ``if``/``else`` statement whose two arms store into the same
        # name is byte-for-byte identical to a merged conditional assignment, so
        # it is deliberately *not* recognised here; keeping it as an ``if``
        # statement matches the original source more closely.

        if allow_return:
            # Nested conditional expressions cannot be split by the linear scans
            # below, because each arm is itself a guarded region rather than a
            # straight-line expression.  Parse the whole range as one recursive
            # value expression instead; it only succeeds when the guards tile
            # the range exactly, which an ``if`` statement body never does.
            parsed = self._parse_value_region(code, instructions, idx, end, stack)
            if parsed is not None:
                value_stack, kinds = parsed
                if (
                    "return" in kinds
                    and self._is_ifexp_value_stack(value_stack, stack)
                    and instructions[end - 1].opname
                    in ("RETURN_VALUE", "RETURN_CONST")
                ):
                    stmts.append(ASTNode.make_Return(value_stack[-1]))
                    stack.clear()
                    return end - idx

            then_return = self._find_ifexp_return(
                instructions, cond_jump + 1, else_idx
            )
            if then_return is not None:
                else_return = self._find_ifexp_return(instructions, else_idx, end)
                if else_return is not None and self._ifexp_tail_is_empty(
                    instructions, else_return + 1, end
                ):
                    then_stack = self._eval_ifexp_expr(
                        code, instructions, cond_jump + 1, then_return, branch_base
                    )
                    else_stack = self._eval_ifexp_expr(
                        code, instructions, else_idx, else_return, branch_base
                    )
                    if self._is_ifexp_value_stack(
                        then_stack, branch_base
                    ) and self._is_ifexp_value_stack(else_stack, branch_base):
                        stmts.append(
                            ASTNode.make_Return(
                                ast.IfExp(
                                    test=cond,
                                    body=then_stack[-1],
                                    orelse=else_stack[-1],
                                )
                            )
                        )
                        stack.clear()
                        return else_return + 1 - idx

        return 0

    def _parse_value_region(
        self,
        code,
        instructions: List[Instruction],
        start: int,
        end: int,
        stack: List[ast.expr],
        depth: int = 0,
    ) -> Optional[Tuple[List[ast.expr], Set[str]]]:
        """Parse ``[start, end)`` as one self-contained value expression.

        The range is consumed in full.  Straight-line expression opcodes are
        evaluated on a private stack until the first control-flow opcode; that
        opcode either terminates the region (a return, or an unconditional jump
        that a surrounding construct will re-target) or is a ``POP_JUMP_IF_*``
        guard whose two arms are themselves value regions delimited by the
        guard's jump target.  Because every arm is bounded by an existing jump
        target, the arms tile the range exactly, which is what makes nested
        conditional expressions reconstructible.  The second element of the
        result is the set of terminator kinds seen anywhere in the region.
        """
        if depth > self._IFEXP_MAX_DEPTH:
            return None
        if start >= end or end > len(instructions):
            return None
        local_stack = list(stack)
        local_stmts: List[ast.stmt] = []
        i = start
        while i < end:
            ins = instructions[i]
            if ins.opname not in self._IFEXP_EXPR_OPS:
                break
            consumed = self._process_instruction(
                ins, instructions, i, code, local_stack, local_stmts,
                is_module=False, limit=end,
            )
            if local_stmts:
                return None
            i += consumed if consumed > 0 else 1
        else:
            return local_stack, set()

        op = instructions[i].opname
        if op in ("RETURN_VALUE", "RETURN_CONST"):
            if i + 1 != end or len(local_stack) != len(stack) + 1:
                return None
            return local_stack, {"return"}
        if op in ("JUMP_ABSOLUTE", "JUMP_FORWARD"):
            if len(local_stack) != len(stack) + 1:
                return None
            return local_stack, {"jump"}
        if op not in ("POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE"):
            return None
        if len(local_stack) != len(stack) + 1:
            return None

        cond = local_stack[-1]
        if op == "POP_JUMP_IF_TRUE":
            cond = ast.UnaryOp(op=ast.Not(), operand=cond)
        branch_base = local_stack[:-1]
        target = int(
            instructions[i].argval
            if instructions[i].argval is not None
            else (instructions[i].arg or 0)
        )
        else_idx = self._find_target_idx(instructions, target)
        if else_idx <= i + 1 or else_idx >= end:
            return None

        then_res = self._parse_value_region(
            code, instructions, i + 1, else_idx, branch_base, depth + 1
        )
        if then_res is None:
            return None
        else_res = self._parse_value_region(
            code, instructions, else_idx, end, branch_base, depth + 1
        )
        if else_res is None:
            return None
        then_stack, then_kinds = then_res
        else_stack, else_kinds = else_res
        if not self._is_ifexp_value_stack(then_stack, branch_base) or not self._is_ifexp_value_stack(
            else_stack, branch_base
        ):
            return None
        value = ast.IfExp(
            test=cond, body=then_stack[-1], orelse=else_stack[-1]
        )
        return branch_base + [value], then_kinds | else_kinds

    def _find_ifexp_condition_jump(
        self, instructions: List[Instruction], start: int, end: int
    ) -> Optional[int]:
        for j in range(start, end):
            op = instructions[j].opname
            if op in ("POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE"):
                return j if j > start else None
            if op not in self._IFEXP_EXPR_OPS:
                return None
        return None

    def _eval_ifexp_expr(
        self,
        code,
        instructions: List[Instruction],
        start: int,
        end: int,
        initial_stack: List[ast.expr],
    ) -> Optional[List[ast.expr]]:
        """Evaluate a straight-line expression range on a private stack."""
        if start >= end or end > len(instructions):
            return None
        local_stack = list(initial_stack)
        local_stmts: List[ast.stmt] = []
        i = start
        while i < end:
            ins = instructions[i]
            if ins.opname not in self._IFEXP_EXPR_OPS:
                return None
            consumed = self._process_instruction(
                ins, instructions, i, code, local_stack, local_stmts,
                is_module=False, limit=end,
            )
            i += consumed if consumed > 0 else 1
        if local_stmts:
            return None
        return local_stack

    def _is_ifexp_value_stack(
        self, result: Optional[List[ast.expr]], base: List[ast.expr]
    ) -> bool:
        return result is not None and len(result) == len(base) + 1

    def _find_ifexp_merge_jump(
        self,
        instructions: List[Instruction],
        cond_jump: int,
        else_idx: int,
        end: int,
    ) -> Optional[Tuple[int, int]]:
        for j in range(cond_jump + 1, else_idx):
            op = instructions[j].opname
            if op not in ("JUMP_FORWARD", "JUMP_ABSOLUTE"):
                continue
            target = int(
                instructions[j].argval
                if instructions[j].argval is not None
                else (instructions[j].arg or 0)
            )
            merge_idx = self._find_target_idx(instructions, target)
            if merge_idx > else_idx and merge_idx <= end:
                return j, merge_idx
        return None

    def _find_ifexp_return(
        self, instructions: List[Instruction], start: int, end: int
    ) -> Optional[int]:
        for j in range(start, end):
            if instructions[j].opname in ("RETURN_VALUE", "RETURN_CONST"):
                return j
        return None

    def _ifexp_tail_is_empty(
        self, instructions: List[Instruction], start: int, end: int
    ) -> bool:
        return all(
            instructions[j].opname in ("NOP", "CACHE")
            for j in range(start, end)
        )

    def _emit_conditional(
        self,
        cond: ast.expr,
        instructions: List[Instruction],
        idx: int,
        code,
        stack: List[ast.expr],
        stmts: List[ast.stmt],
        target: int,
    ) -> int:
        """Emit an ``if``/``while`` construct for a POP_JUMP_IF_* instruction."""
        target_idx = self._find_target_idx(instructions, target)
        if target_idx <= idx and self._loop_stack and target == self._loop_stack[-1][0]:
            # A condition that jumps back to the active loop head is an ``if`` in
            # the loop body, not a new loop.  The following unconditional jump is
            # the loop back edge; exclude it from the branch body.
            body_start = idx + 1
            body_end = len(instructions)
            for j in range(body_start, len(instructions)):
                ins = instructions[j]
                if ins.opname in ("JUMP_ABSOLUTE", "JUMP_FORWARD"):
                    jump_target = int(ins.argval if ins.argval is not None else 0)
                    if jump_target <= ins.offset:
                        body_end = j
                        break
            body_stmts = self._emit_statements(
                code, instructions, is_module=False, start=body_start, end=body_end
            )
            if body_stmts:
                stmts.append(ast.If(test=cond, body=body_stmts, orelse=[]))
                return max(1, body_end + 1 - idx)
            return 1
        body_start, body_end, else_start, else_end, end_idx = self._split_branch(instructions, idx, target)
        back_edge = self._find_loop_back_edge(instructions, body_start, body_end)
        if back_edge is not None:
            exit_offset = (
                instructions[end_idx].offset
                if end_idx < len(instructions)
                else instructions[-1].offset + 2
            )
            head_offset = instructions[body_start].offset
            body_stmts = self._emit_loop_body(
                code, instructions, body_start, back_edge, head_offset, exit_offset,
            )
            stmts.append(ast.While(test=cond, body=body_stmts, orelse=[]))
            return max(1, end_idx - idx)
        # ``if cond: break`` has an empty then-branch that is nothing but a jump to
        # the merge point -- the "else" region is really the fall-through code.
        if body_start == body_end and else_start is not None and else_end == end_idx:
            jump_stmt = self._classify_jump(instructions, instructions[body_end])
            if jump_stmt is not None:
                stmts.append(ast.If(test=cond, body=[jump_stmt], orelse=[]))
                return max(1, end_idx - idx)
        body_stmts = self._emit_statements(
            code, instructions, is_module=False, start=body_start, end=body_end
        )
        else_stmts: List[ast.stmt] = []
        if else_start is not None:
            else_stmts = self._emit_statements(
                code, instructions, is_module=False, start=else_start, end=else_end
            )
        if not body_stmts and not else_stmts:
            return max(1, end_idx - idx)
        stmts.append(
            ast.If(test=cond, body=body_stmts or [ast.Pass()], orelse=else_stmts)
        )
        if self._branch_closes_loop(instructions, body_end, end_idx):
            # The branch ended with ``break``/``continue``, so ``end_idx`` points
            # at the loop exit rather than at this ``if``'s merge point.  The
            # instructions in between are loop-body fall-through code and must
            # still be emitted by the enclosing range.
            return max(1, body_end - idx)
        return max(1, end_idx - idx)

    def _branch_closes_loop(
        self, instructions: List[Instruction], body_end: int, end_idx: int
    ) -> bool:
        """Whether ``end_idx`` is a loop exit rather than the branch merge point."""
        if body_end <= 0 or body_end >= len(instructions) or end_idx <= body_end:
            return False
        return self._classify_jump(instructions, instructions[body_end - 1]) is not None

    def _match_loop_jump(self, target: int) -> Optional[str]:
        """Classify an unconditional jump against every enclosing loop.

        ``continue`` is a jump back to the innermost loop head; ``break`` is a
        jump at or past any enclosing loop exit.  The search walks the whole
        stack because a ``break`` in an inner loop may land on the head or the
        exit of an *outer* loop.
        """
        for depth, (head_offset, exit_offset) in enumerate(reversed(self._loop_stack)):
            if target == head_offset:
                return "continue" if depth == 0 else "break"
            if target >= exit_offset:
                return "break"
        return None

    def _classify_jump(
        self, instructions: List[Instruction], instr: Instruction
    ) -> Optional[ast.stmt]:
        """Map an unconditional jump to ``break``/``continue`` when inside a loop."""
        if not self._loop_stack:
            return None
        target = _jump_target(instr)
        if target is None:
            # Not a jump at all.  Callers reach here with whatever instruction a
            # landing index happens to point at, and a non-jump's ``argval`` is
            # its operand -- a variable name, say -- so coercing it to an int is
            # how ``while True: try: ... break ... finally: ...`` used to die
            # with ``ValueError: invalid literal for int()``.
            return None
        kind = self._match_loop_jump(target)
        if kind == "continue":
            return ast.Continue()
        if kind == "break":
            return ast.Break()
        return None

    def _consume_back_edge(
        self, instructions: List[Instruction], idx: int
    ) -> int:
        """Skip the jump back to the loop head that closes a ``try``/``finally``.

        CPython emits it where the protected range ends, so a ``try``/
        ``finally`` that is the last statement of a loop body is followed by a
        back edge the source never wrote.  It is only implicit when every
        instruction between it and the loop exit belongs to the handler copy of
        the ``finally`` clause, so a real ``continue`` in the body still reads
        as one.
        """
        if idx is None or idx >= len(instructions):
            return idx
        instr = instructions[idx]
        if instr.opname not in ("JUMP_ABSOLUTE", "JUMP_FORWARD"):
            return idx
        if not isinstance(
            self._classify_jump(instructions, instr), ast.Continue
        ):
            return idx
        exit_offset = self._loop_stack[-1][1]
        for j in range(idx + 1, len(instructions)):
            if instructions[j].offset >= exit_offset:
                break
            if instructions[j].opname == "RERAISE":
                # The handler re-raises, so nothing after it in the body can run.
                break
            if not any(
                r_start <= j < r_end for r_start, r_end in self._handled_ranges
            ):
                return idx
        return idx + 1

    def _continue_over_handler(
        self, instructions: List[Instruction], idx: int
    ) -> Tuple[Optional[ast.stmt], int]:
        """Recover the ``continue`` written after a ``try``/``finally``.

        3.9 ends the protected range with the back edge itself, so a
        ``continue`` after the block lands on a second one and is told apart by
        the extra jump.  3.10 and 3.11 instead close the range with a *forward*
        jump over the handler and put the single back edge after it, so the
        source-level ``continue`` is that forward jump.  3.12 elides the
        ``continue`` entirely and is indistinguishable from its absence.
        """
        if idx is None or idx >= len(instructions) or not self._loop_stack:
            return None, idx
        instr = instructions[idx]
        target = _jump_target(instr)
        if target is None or target <= instr.offset:
            return None, idx
        landing = self._find_target_idx(instructions, target)
        if landing >= len(instructions):
            return None, idx
        if not isinstance(
            self._classify_jump(instructions, instructions[landing]), ast.Continue
        ):
            return None, idx
        return ast.Continue(), landing + 1

    def _find_loop_back_edge(
        self, instructions: List[Instruction], body_start: int, body_end: int
    ) -> Optional[int]:
        """Detect ``while cond:`` -- body ends with a jump back to the condition."""
        if body_start >= body_end:
            return None
        head_offset = instructions[body_start].offset
        for j in range(body_end - 1, max(body_start, body_end - 3) - 1, -1):
            ins = instructions[j]
            if ins.opname in ("JUMP_ABSOLUTE", "JUMP_FORWARD"):
                jt = int(ins.argval if ins.argval is not None else (ins.arg or 0))
                if jt == head_offset:
                    return j
                return None
        return None

    def _find_loop_body_end(
        self,
        instructions: List[Instruction],
        loop_idx: int,
        body_start: int,
        end_idx: int,
    ) -> int:
        """Index just past a ``for`` body that starts at ``body_start``.

        The implicit back edge to ``FOR_ITER`` only closes the body when it is
        the instruction right before the loop exit.  A source-level ``continue``
        jumps back to the same head from further inside, and the statements
        behind it up to the exit are still body code, so the scan has to keep
        looking instead of stopping at the first backward jump.

        What follows such a jump may also be a copy of the code after the loop,
        which the compiler emits as the landing pad of a ``break``; that copy
        belongs to neither the body nor this loop and is cut off.
        """
        back_edge: Optional[int] = None
        for j in range(end_idx - 1, body_start - 1, -1):
            ins = instructions[j]
            if ins.opname not in ("JUMP_ABSOLUTE", "JUMP_FORWARD"):
                continue
            jt = int(ins.argval if ins.argval is not None else (ins.arg or 0))
            if jt <= instructions[loop_idx].offset:
                back_edge = j
            break
        if back_edge is None:
            return end_idx
        if back_edge == end_idx - 1:
            return back_edge
        tail = self._find_duplicated_tail(instructions, back_edge, end_idx)
        return tail if tail is not None else end_idx

    @staticmethod
    def _find_duplicated_tail(
        instructions: List[Instruction], start: int, end_idx: int
    ) -> Optional[int]:
        """Largest ``s`` in ``(start, end_idx)`` whose suffix repeats at ``end_idx``.

        ``instructions[s:end_idx]`` is compared against the instructions
        starting at the loop exit; the largest match is the copy the compiler
        duplicated after the loop.
        """
        total = len(instructions)
        best: Optional[int] = None
        for s in range(end_idx - 1, start, -1):
            length = end_idx - s
            if end_idx + length > total:
                break
            for k in range(length):
                left = instructions[s + k]
                right = instructions[end_idx + k]
                if left.opname != right.opname or left.arg != right.arg:
                    break
            else:
                best = s
        return best

    def _split_branch(
        self, instructions: List[Instruction], idx: int, target: int
    ) -> Tuple[int, int, Optional[int], Optional[int], int]:
        """Split a conditional branch into index ranges.

        Returns ``(body_start, body_end, else_start, else_end, end_idx)``.  A
        backward jump inside the body belongs to a loop back edge and must not be
        mistaken for an ``else`` branch.
        """
        current_end = self._find_target_idx(instructions, target)
        body_start = idx + 1
        body_end = current_end
        else_start: Optional[int] = None
        else_end: Optional[int] = None
        end_idx = current_end
        i = body_start
        while i < current_end:
            ins = instructions[i]
            if ins.opname in ("JUMP_FORWARD", "JUMP_ABSOLUTE"):
                jt = int(ins.argval if ins.argval is not None else (ins.arg or 0))
                if jt <= ins.offset:
                    i += 1
                    continue
                after = self._find_target_idx(instructions, jt)
                if after > current_end:
                    if self._classify_jump(instructions, ins) is not None:
                        # ``break``/``continue`` closing the branch is a statement of
                        # the branch, not the jump that opens an ``else``; the code
                        # after the target is the loop remainder, not an else arm.
                        body_end = i + 1
                        end_idx = after
                        break
                    body_end = i
                    else_start = current_end
                    else_end = after
                    end_idx = after
                    break
            i += 1
        return body_start, body_end, else_start, else_end, end_idx

    def _process_yield_from(
        self,
        instr: Instruction,
        instructions: List[Instruction],
        idx: int,
        code,
        stack: List[ast.expr],
        stmts: List[ast.stmt],
        limit: Optional[int] = None,
        node=ast.YieldFrom,
    ) -> int:
        """Rebuild ``yield from``/``await`` from the iterator or awaitable op.

        The compiler asks for the sub-iterator (``GET_YIELD_FROM_ITER``) or the
        awaitable (``GET_AWAITABLE``), pushes the value sent back, and hands both
        to ``YIELD_FROM``.  The result is a statement expression when a
        ``POP_TOP`` follows, otherwise a value for whatever consumes the yield.
        """
        end = len(instructions) if limit is None else limit
        j = idx + 1
        if j < end and instructions[j].opname == "LOAD_CONST":
            j += 1
        if j >= end or instructions[j].opname != "YIELD_FROM" or not stack:
            return 1
        j += 1
        value = node(value=stack.pop())
        if j < end and instructions[j].opname == "POP_TOP":
            stmts.append(ast.Expr(value=value))
            return j + 1 - idx
        stack.append(value)
        return j - idx

    def _process_loop(
        self,
        instr: Instruction,
        instructions: List[Instruction],
        idx: int,
        code,
        stack: List[ast.expr],
        stmts: List[ast.stmt],
        limit: Optional[int] = None,
    ) -> int:
        opname = instr.opname
        if opname == "GET_ITER":
            return 1
        if opname == "FOR_ITER":
            if not stack:
                return 1
            target = int(instr.argval if instr.argval is not None else (instr.arg or 0))
            end_idx = self._find_target_idx(instructions, target)
            iter_obj = stack[-1]
            loop_var = None
            body_start = idx + 1
            # ``for a, b in it`` starts with an ``UNPACK_SEQUENCE`` followed by
            # exactly that many stores.
            if idx + 1 < len(instructions) and instructions[idx + 1].opname == "UNPACK_SEQUENCE":
                count = instructions[idx + 1].arg or 0
                unpacked, after = self._collect_store_targets(instructions, idx + 2, count)
                if count > 0 and len(unpacked) == count:
                    loop_var = (
                        unpacked[0]
                        if count == 1
                        else ast.Tuple(elts=unpacked, ctx=ast.Store())
                    )
                    body_start = after
            if loop_var is None:
                for j in range(idx + 1, min(end_idx, idx + 3)):
                    if instructions[j].opname in ("STORE_FAST", "STORE_NAME",
                                                 "STORE_GLOBAL", "STORE_DEREF"):
                        # A loop variable that a nested function closes over
                        # lives in a cell, so the compiler stores it with
                        # ``STORE_DEREF`` instead of ``STORE_FAST``.
                        loop_var = ASTNode.make_Name(str(instructions[j].argval), ast.Store())
                        body_start = j + 1
                        break
            if loop_var is None:
                return 1
            stack.pop()
            body_end = self._find_loop_body_end(
                instructions, idx, body_start, end_idx
            )
            exit_offset = (
                instructions[end_idx].offset
                if end_idx < len(instructions)
                else instructions[-1].offset + 2
            )
            body_stmts = self._emit_loop_body(
                code, instructions, body_start, body_end,
                instructions[idx].offset, exit_offset,
            )
            stmts.append(ast.For(target=loop_var, iter=iter_obj, body=body_stmts, orelse=[]))
            # A ``for``/``else`` tail is emitted by the enclosing range: continuing
            # in place keeps the expression stack, so a following loop still sees
            # the iterator it pushed.
            return max(1, end_idx - idx)
        return 1

    def _process_async_for(
        self,
        instr: Instruction,
        instructions: List[Instruction],
        idx: int,
        code,
        stack: List[ast.expr],
        stmts: List[ast.stmt],
        limit: Optional[int] = None,
    ) -> int:
        """Rebuild ``async for`` from ``GET_AITER``/``END_ASYNC_FOR``.

        The back edge lands on the 3.9 ``SETUP_FINALLY`` that guards the await,
        or -- from 3.11 on, which has no such guard -- on the ``GET_ANEXT``
        behind it.  Either way the body runs from the store of the loop target
        to that back edge, and ``END_ASYNC_FOR`` is the landing pad for
        ``StopAsyncIteration``.
        """
        if not stack:
            return 1
        iter_obj = stack[-1]
        end = len(instructions) if limit is None else limit
        head_idx = idx + 1
        anext_idx = head_idx
        if head_idx < end and instructions[head_idx].opname == "SETUP_FINALLY":
            anext_idx = head_idx + 1
        if anext_idx >= end or instructions[anext_idx].opname != "GET_ANEXT":
            return 1
        j = anext_idx + 1
        if j < end and instructions[j].opname == "LOAD_CONST":
            j += 1
        if j >= end or instructions[j].opname != "YIELD_FROM":
            return 1
        j += 1
        if j < end and instructions[j].opname == "POP_BLOCK":
            j += 1
        if j >= end or instructions[j].opname not in (
            "STORE_FAST", "STORE_NAME", "STORE_GLOBAL", "STORE_DEREF",
        ):
            return 1
        loop_var = ASTNode.make_Name(str(instructions[j].argval), ast.Store())
        body_start = j + 1
        exit_idx = None
        for k in range(body_start, end):
            if instructions[k].opname == "END_ASYNC_FOR":
                exit_idx = k
                break
        if exit_idx is None:
            return 1
        body_end = self._find_loop_body_end(
            instructions, head_idx, body_start, exit_idx
        )
        body_stmts = self._emit_loop_body(
            code, instructions, body_start, body_end,
            instructions[head_idx].offset, instructions[exit_idx].offset,
        )
        stack.pop()
        stmts.append(
            ast.AsyncFor(
                target=loop_var, iter=iter_obj,
                body=body_stmts, orelse=[],
            )
        )
        return max(1, exit_idx - idx + 1)

    _STMT_END_OPS = (
        "POP_TOP", "RETURN_VALUE", "RETURN_CONST", "STORE_FAST", "STORE_NAME",
        "STORE_GLOBAL", "STORE_ATTR", "STORE_SUBSCR", "PRINT_EXPR",
    )

    _STMT_START_OPS = (
        "POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE", "FOR_ITER", "GET_ITER",
        "SETUP_FINALLY", "SETUP_WITH", "JUMP_ABSOLUTE", "JUMP_FORWARD",
    )

    def _process_with(
        self,
        instr: Instruction,
        instructions: List[Instruction],
        idx: int,
        code,
        stack: List[ast.expr],
        stmts: List[ast.stmt],
    ) -> int:
        """Rebuild ``with expr as target:`` from a ``SETUP_WITH`` block.

        CPython pushes the context expression, calls ``__enter__`` and stores
        the result; the matching ``POP_BLOCK`` marks the end of the body and the
        following forward jump points at the instruction after the implicit
        ``__exit__`` call.  The exception cleanup that ``SETUP_WITH`` targets is
        compiler-generated and is therefore dropped.
        """
        if not stack:
            return 1
        context_expr = stack.pop()
        target = self._jump_target(instr)
        handler_start_idx = self._find_target_idx(instructions, target)
        pop_idx = self._find_pop_block(instructions, idx, target)
        if pop_idx <= idx or pop_idx > handler_start_idx:
            return 1
        body_start = idx + 1
        body_stack: List[ast.expr] = []
        optional_vars: Optional[ast.expr] = None
        if instructions[body_start].opname in (
            "STORE_FAST", "STORE_NAME", "STORE_DEREF", "STORE_GLOBAL"
        ):
            optional_vars = ASTNode.make_Name(
                str(instructions[body_start].argval), ast.Store()
            )
            body_start += 1
        body = self._emit_statements(
            code, instructions, is_module=False, start=body_start, end=pop_idx,
            out_stack=body_stack,
        )
        # Nothing between the body's own statements and the block teardown is
        # source level.  Where the teardown lands decides how the body leaves:
        # a ``RETURN_VALUE`` is a ``return``, a jump the loop stack recognises
        # is a ``break``/``continue``, and anything else falls through.
        term_idx = self._with_exit_terminator(
            instructions, pop_idx, handler_start_idx, bool(body_stack)
        )
        term = instructions[term_idx] \
            if 0 <= term_idx < len(instructions) else None
        abrupt: Optional[ast.stmt] = None
        if term is not None and term.opname in ("JUMP_ABSOLUTE", "JUMP_FORWARD"):
            candidate = self._classify_jump(instructions, term)
            if isinstance(candidate, ast.Break):
                abrupt = candidate
            elif isinstance(candidate, ast.Continue) and not body:
                # A jump back to the loop head behind the teardown is the
                # loop's own back edge when the body ran to its end -- the
                # ``with`` was the last statement of the loop body.  A
                # ``continue`` written in the body compiles to the same jump,
                # but only an empty body can tell the two apart: a ``continue``
                # leaves the body at once.
                abrupt = candidate

        returned = _NO_RETURN
        if term is not None and term.opname in ("RETURN_VALUE", "LOAD_CONST"):
            returned = self._with_return_value(instructions, term_idx, body_stack)

        merge_idx = self._find_stmt_run_end(instructions, pop_idx, handler_start_idx)
        if returned is not _NO_RETURN:
            # The teardown also emits a bare ``return`` for the value it could
            # not attribute; drop it now that the real one is known.
            while body and _is_bare_return(body[-1]):
                body.pop()
            body.append(ast.Return(value=returned))
            # A ``return`` leaves the function, so the block's own exception
            # handler is unreachable and the enclosing range must resume past
            # it rather than at its ``WITH_EXCEPT_START``.
            merge_idx = self._find_with_handler_end(instructions, handler_start_idx)
        elif abrupt is not None:
            # ``break``/``continue`` leave through the block teardown, so the
            # body has no statements of its own left to resume from.  The
            # exception handler is compiler-generated and ends the block.
            body.append(abrupt)
            merge_idx = self._find_with_handler_end(instructions, handler_start_idx)
        else:
            for j in range(pop_idx, handler_start_idx):
                if instructions[j].opname in ("JUMP_FORWARD", "JUMP_ABSOLUTE"):
                    after = self._find_target_idx(instructions, self._jump_target(instructions[j]))
                    if after >= handler_start_idx:
                        merge_idx = after
                        break
        with_cls = (ast.AsyncWith if instr.opname == "SETUP_ASYNC_WITH"
                       else ast.With)
        items = [ast.withitem(context_expr=context_expr,
                              optional_vars=optional_vars)]
        # ``with a as x, b as y:`` compiles to consecutive ``SETUP_WITH`` blocks
        # whose bodies coincide, so the inner one reads back as the first
        # statement of the outer body.  Fold such a directly nested block into
        # this one so the two managers are printed as the single source
        # statement they came from.  Only a body that ends where the outer one
        # does -- nothing but an abrupt exit (``return`` / ``break`` /
        # ``continue``) the teardown handed back -- is folded; a statement that
        # genuinely runs after the inner block exits stays where it is and
        # keeps the nesting.
        while body and type(body[0]) is with_cls \
                and all(isinstance(stmt, (ast.Return, ast.Break, ast.Continue))
                        for stmt in body[1:]):
            inner = body[0]
            items.extend(inner.items)
            inner_body = list(inner.body)
            tail = body[1:]
            if tail and len(inner_body) == 1 \
                    and isinstance(inner_body[0], ast.Pass):
                # The empty body the inner block synthesised is not source; the
                # real body is the value its teardown handed back.
                inner_body = []
            body = inner_body + tail
        stmts.append(
            with_cls(items=items, body=body or [ast.Pass()])
        )
        # A value still pending when the body ends belongs to the enclosing
        # statement: ``with a as x, b as y: return x + y`` evaluates the
        # expression inside both blocks and only returns after both have
        # exited, so the block teardown leaves it on the stack.  Hand the
        # leftovers back to the caller unless a ``return`` claimed them.
        if returned is _NO_RETURN:
            stack.extend(body_stack)
        return max(1, merge_idx - idx)

    #: Opcodes of the implicit ``__exit__(None, None, None)`` call that closes a
    #: ``with`` body.
    _WITH_TEARDOWN_OPS = frozenset((
        "ROT_TWO", "ROT_THREE", "ROT_FOUR", "LOAD_CONST", "DUP_TOP",
        "DUP_TOP_TWO", "POP_TOP", "CALL_FUNCTION", "CALL_METHOD",
        "CALL_FUNCTION_KW", "CALL_METHOD_KW",
    ))
    #: Opcodes that may sit between that call and the statement leaving the
    #: block: the discarded result, the ``await`` an ``async with`` runs on the
    #: bound ``__aexit__``, an enclosing loop's iterator teardown and an
    #: enclosing ``try``/``finally`` block.
    _WITH_UNWIND_OPS = frozenset((
        "ROT_TWO", "ROT_THREE", "ROT_FOUR", "POP_TOP", "POP_BLOCK",
    ))

    def _with_exit_terminator(
        self,
        instructions: List[Instruction],
        pop_idx: int,
        limit: int,
        body_value: bool = False,
    ) -> int:
        """Index of the instruction that ends the implicit ``__exit__`` call.

        A body returning a constant has nothing on the virtual stack, so the
        compiler materialises the value *after* the call; the ``LOAD_CONST`` it
        lands on is therefore part of the terminator, not of the teardown.
        Returns ``-1`` when the block closes without a recognisable teardown.

        *body_value* says whether the body left a value on the stack.  A
        ``POP_BLOCK`` behind the teardown closes an *enclosing* block, so the
        code behind it belongs to that block -- unless the ``with`` body left a
        value behind, in which case the ``return`` that follows the pop is the
        body's own.
        """
        i = pop_idx + 1
        while i < limit and instructions[i].opname in self._WITH_TEARDOWN_OPS:
            opname = instructions[i].opname
            if opname in ("CALL_FUNCTION", "CALL_METHOD",
                          "CALL_FUNCTION_KW", "CALL_METHOD_KW"):
                i += 1
                # An ``async with`` awaits the bound ``__aexit__`` on the way
                # out: GET_AWAITABLE / LOAD_CONST None / YIELD_FROM.
                if i + 2 < len(instructions) \
                        and instructions[i].opname == "GET_AWAITABLE" \
                        and instructions[i + 1].opname == "LOAD_CONST" \
                        and instructions[i + 2].opname == "YIELD_FROM":
                    i += 3
                # Skip only the discarded result and an enclosing loop's
                # teardown pairs.  A ``POP_BLOCK`` closes an *enclosing*
                # block, so the walk has to stop in front of it: whatever
                # follows belongs to that block, not to this ``with``.  3.9
                # jumps over the ``with``'s own handler here, 3.11/3.12 close
                # the enclosing ``try`` instead.
                while i < len(instructions):
                    nxt = instructions[i].opname
                    if nxt == "POP_TOP":
                        i += 1
                        continue
                    if nxt == "POP_BLOCK":
                        if not body_value:
                            break
                        i += 1
                        continue
                    if nxt in ("ROT_TWO", "ROT_THREE", "ROT_FOUR") \
                            and not self._starts_with_teardown(instructions, i):
                        i += 1
                        continue
                    break
                # The block's handler may have been dropped from the stream
                # entirely; walking off the end leaves no terminator to read.
                return i if i < len(instructions) else -1
            i += 1
        return -1

    def _with_return_value(
        self, instructions: List[Instruction], term_idx: int, body_stack: List[ast.expr]
    ):
        """The value a ``with`` body returns, or ``_NO_RETURN`` when it does not.

        Leaving a ``with`` body through ``return`` rotates the pending value
        below the bound ``__exit__`` method, calls the method with the three
        ``None`` arguments, discards its result and only then returns the value.
        None of that is source level, so the whole run has to be recognised as
        the block's own teardown.  A body returning a constant has nothing left
        on the virtual stack, so that constant is read back from the
        ``LOAD_CONST`` the terminator sits on.
        """
        opname = instructions[term_idx].opname
        if opname == "LOAD_CONST":
            if term_idx + 1 < len(instructions) and \
                    instructions[term_idx + 1].opname == "RETURN_VALUE":
                return ASTNode.make_Constant(instructions[term_idx].argval)
            return _NO_RETURN
        if opname == "RETURN_VALUE" and body_stack:
            return body_stack[-1]
        return _NO_RETURN

    def _find_with_handler_end(
        self, instructions: List[Instruction], handler_start_idx: int
    ) -> int:
        """Index just past a ``with`` block's compiler-generated exception handler.

        The handler ends with the jump back to the enclosing loop, which is the
        only unconditional transfer in it; the ``RERAISE`` in the middle belongs
        to the ``WITH_EXCEPT_START`` protocol.
        """
        for i in range(handler_start_idx, len(instructions)):
            if instructions[i].opname in (
                "JUMP_ABSOLUTE", "JUMP_FORWARD", "RETURN_VALUE", "RETURN_CONST"
            ):
                return i + 1
        return len(instructions)

    def _find_stmt_run_end(self, instructions: List[Instruction], start: int, hard_end: int) -> int:
        """Advance past a run of complete simple statements starting at ``start``."""
        i = start
        while i < hard_end:
            ins = instructions[i]
            if i > start and (ins.is_jump_target or ins.opname in self._STMT_START_OPS):
                break
            if ins.opname in self._STMT_END_OPS:
                return i + 1
            i += 1
        return i

    def _find_target_idx(self, instructions: List[Instruction], target_offset: int) -> int:
        for i, instr in enumerate(instructions):
            if instr.offset >= target_offset:
                return i
        return len(instructions)

    def _find_pop_block(self, instructions: List[Instruction], setup_idx: int, target_offset: int) -> int:
        """Find the index of the POP_BLOCK that closes the block started at setup_idx.

        Must skip nested SETUP_* blocks (their POP_BLOCKs belong to the nested block).

        For a ``with`` block the candidates are filtered by their teardown: a
        ``return`` inside the body pops the block on its own path, so a block
        with an early exit has two depth-one ``POP_BLOCK``s.  The early one is
        followed by a teardown that leaves the function; the body's real end is
        the first candidate whose teardown *does not* return, because anything
        after that belongs to an enclosing block (the outer ``with`` of a
        ``with a as x, b as y:`` pair closes right after the inner teardown and
        would otherwise be mistaken for this block's end).

        For ``try``/``finally`` and ``try``/``except`` the *last* depth-one
        ``POP_BLOCK`` is the end of the range: an early ``break``/``continue``/
        ``return`` unwinds the block on one path, and the normal path pops it
        again later.
        """
        try_end_idx = self._find_target_idx(instructions, target_offset)
        depth = 1
        setup_ops = {"SETUP_FINALLY", "SETUP_EXCEPT", "SETUP_WITH",
                       "SETUP_ASYNC_WITH", "SETUP_LOOP"}
        is_with = instructions[setup_idx].opname in (
            "SETUP_WITH", "SETUP_ASYNC_WITH")
        is_finally = instructions[setup_idx].opname == "SETUP_FINALLY" \
            and self._is_bare_finally(instructions, try_end_idx)
        clause_len = 0
        if is_finally:
            clause_len = self._finally_clause_length(instructions, try_end_idx)
        candidates: List[int] = []
        for i in range(setup_idx + 1, try_end_idx):
            op = instructions[i].opname
            if op in setup_ops:
                depth += 1
            elif op == "POP_BLOCK":
                if depth <= 1:
                    # Our own block.  Keep the counter at 1 rather than letting
                    # it reach zero: an early ``break``/``continue``/``return``
                    # pops the same block on one path, and the normal path pops
                    # it again later, so the two would otherwise cancel out and
                    # hide the real end of the range.
                    candidates.append(i)
                    depth = 1
                else:
                    # depth > 1: this POP_BLOCK belongs to a nested block.
                    depth -= 1
        if not candidates:
            return try_end_idx
        candidates = self._filter_block_closes(
            instructions, setup_idx, try_end_idx, candidates)
        if not candidates:
            return try_end_idx
        if len(candidates) == 1:
            return candidates[0]
        if not (is_with or (is_finally and clause_len)):
            # A block nested in another one closes right in front of the
            # enclosing block's close, so the two ``POP_BLOCK``s sit next to
            # each other.  The first of them is the inner block's -- the
            # ``try`` of a ``try`` inside a ``with``, say.
            for i in candidates:
                end = self._after_block_cleanup(
                    instructions, i + 1, try_end_idx, is_with, clause_len)
                if end is not None and end < len(instructions) \
                        and instructions[end].opname == "POP_BLOCK":
                    return i
            return candidates[-1]
        # The handler's unwind path repeats an enclosing block's close, and
        # that copy is unreachable from the entry along ordinary control flow.
        # Dropping it leaves only the block's own closes.
        reachable = self._reachable_indices(instructions)
        on_path = [i for i in candidates if i in reachable]
        if on_path:
            candidates = on_path
        # A nested block whose body leaves abruptly runs the enclosing block's
        # cleanup right after its own, so its close is immediately followed by
        # the enclosing ``POP_BLOCK``.  That is the inner body's end; the
        # enclosing close belongs to the outer block.
        for i in candidates:
            end = self._after_block_cleanup(
                instructions, i + 1, try_end_idx, is_with, clause_len)
            if end is not None and end < len(instructions) \
                    and instructions[end].opname == "POP_BLOCK":
                return i
        # A body that falls off its end is closed by a forward jump over the
        # handler.  A ``return`` inside an ``if`` pops the block on its own
        # path too, but its cleanup ends in ``RETURN_VALUE``; the jump is the
        # normal completion and therefore the body's real end.
        for i in reversed(candidates):
            end = self._after_block_cleanup(
                instructions, i + 1, try_end_idx, is_with, clause_len)
            if end is not None and end < len(instructions) \
                    and instructions[end].opname in ("JUMP_FORWARD",
                                                     "JUMP_ABSOLUTE"):
                return i
        return candidates[-1]

    def _filter_block_closes(
        self,
        instructions: List[Instruction],
        setup_idx: int,
        try_end_idx: int,
        candidates: List[int],
    ) -> List[int]:
        """Drop the closes that do not belong to the block being closed.

        The stock layout only offers one close per block, so nothing has to be
        filtered; versions that park a nested block's handler inside the range
        override this.
        """
        return candidates

    def _after_block_cleanup(
        self,
        instructions: List[Instruction],
        start: int,
        limit: int,
        is_with: bool,
        clause_len: int,
    ) -> Optional[int]:
        """Index just past the cleanup a block runs when its body ends.

        A ``with`` runs ``__exit__``; a ``try``/``finally`` runs an inlined
        copy of the clause.  Both are followed by the loop teardown an abrupt
        exit needs, which is skipped here so the caller can look at what
        follows the block itself.
        """
        if is_with:
            return self._teardown_end(instructions, start, limit)
        k = start + clause_len
        while k + 1 < len(instructions) \
                and instructions[k].opname in ("ROT_TWO", "ROT_THREE",
                                               "ROT_FOUR") \
                and instructions[k + 1].opname == "POP_TOP":
            k += 2
        if k < len(instructions) and instructions[k].opname == "POP_TOP":
            k += 1
        return k

    def _reachable_indices(self, instructions: List[Instruction]) -> set:
        """Indices reachable from the entry along ordinary control flow.

        Exception handlers are entered by the interpreter rather than by a
        jump, so the walk never steps into one: a ``POP_BLOCK`` that only
        appears inside a handler is a duplicate of an enclosing block's close,
        emitted for the unwind path.
        """
        n = len(instructions)
        if not n:
            return set()
        conditional = {
            "POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE",
            "POP_JUMP_FORWARD_IF_FALSE", "POP_JUMP_FORWARD_IF_TRUE",
            "POP_JUMP_BACKWARD_IF_FALSE", "POP_JUMP_BACKWARD_IF_TRUE",
            "JUMP_IF_FALSE_OR_POP", "JUMP_IF_TRUE_OR_POP", "FOR_ITER",
            "SEND", "JUMP_IF_NOT_EXC_MATCH", "CHECK_EXC_MATCH",
        }
        unconditional = {"JUMP_ABSOLUTE", "JUMP_FORWARD", "JUMP_BACKWARD",
                         "JUMP"}
        terminal = {"RETURN_VALUE", "RETURN_CONST", "RAISE_VARARGS",
                    "RERAISE"}
        seen = set()
        work = [0]
        while work:
            i = work.pop()
            while 0 <= i < n and i not in seen:
                seen.add(i)
                ins = instructions[i]
                op = ins.opname
                if op in terminal:
                    break
                if op in unconditional:
                    target = self._jump_target(ins)
                    if target is not None:
                        work.append(self._find_target_idx(instructions, target))
                    break
                if op in conditional:
                    target = self._jump_target(ins)
                    if target is not None:
                        work.append(self._find_target_idx(instructions, target))
                    i += 1
                    continue
                i += 1
        return seen

    def _starts_with_teardown(self, instructions: List[Instruction], start: int) -> bool:
        """True when *start* begins the ``__exit__(None, None, None)`` call.

        A ``with`` body is closed by a rotation, three ``None`` operands and a
        call; recognising the sequence is what tells an enclosing ``with``
        block's ``POP_BLOCK`` apart from a loop's, since only the former is
        followed by another teardown.
        """
        limit = len(instructions)
        i = start
        while i < limit and instructions[i].opname in (
                "ROT_TWO", "ROT_THREE", "ROT_FOUR", "SWAP"):
            i += 1
        operands = 0
        while i < limit and instructions[i].opname in (
                "LOAD_CONST", "LOAD_SMALL_INT", "DUP_TOP", "DUP_TOP_TWO", "COPY"):
            if instructions[i].opname in ("LOAD_CONST", "LOAD_SMALL_INT") \
                    and instructions[i].argval is not None:
                break
            operands += 1
            i += 1
        return operands >= 3 and i < limit and instructions[i].opname in (
            "CALL_FUNCTION", "CALL_METHOD", "CALL_FUNCTION_KW", "CALL_METHOD_KW")

    def _teardown_end(
        self, instructions: List[Instruction], start: int, limit: int
    ) -> Optional[int]:
        """Index just past the ``__exit__`` teardown that begins at *start*.

        Returns ``None`` when no complete teardown starts there.
        """
        i = start
        while i < limit and instructions[i].opname in (
                "ROT_TWO", "ROT_THREE", "ROT_FOUR", "SWAP"):
            i += 1
        operands = 0
        while i < limit and instructions[i].opname in (
                "LOAD_CONST", "LOAD_SMALL_INT", "DUP_TOP", "DUP_TOP_TWO", "COPY"):
            if instructions[i].opname in ("LOAD_CONST", "LOAD_SMALL_INT") \
                    and instructions[i].argval is not None:
                break
            operands += 1
            i += 1
        if operands < 3 or i >= limit:
            return None
        if instructions[i].opname not in (
                "CALL_FUNCTION", "CALL_METHOD", "CALL_FUNCTION_KW",
                "CALL_METHOD_KW"):
            return None
        i += 1
        if i < limit and instructions[i].opname == "POP_TOP":
            i += 1
        return i

    def _skip_nested_try(self, instructions: List[Instruction], setup_idx: int) -> int:
        """Return the index just past a nested try statement that starts at setup_idx."""
        setup_instr = instructions[setup_idx]
        target = int(setup_instr.argval if setup_instr.argval is not None else (setup_instr.arg or 0))
        handler_start = self._find_target_idx(instructions, target)
        pop_idx = self._find_pop_block(instructions, setup_idx, target)
        if pop_idx < handler_start:
            pop_idx = handler_start
        return self._find_post_handler_idx(instructions, pop_idx, handler_start, target)

    def _find_post_handler_idx(
        self,
        instructions: List[Instruction],
        pop_idx: int,
        handler_start_idx: int,
        target_offset: int,
    ) -> int:
        """Index just past a whole try statement (handlers plus implicit ``as e`` finally)."""
        n = len(instructions)
        i = handler_start_idx
        while i < n:
            op = instructions[i].opname
            if op in ("SETUP_FINALLY", "SETUP_EXCEPT") and i > handler_start_idx:
                i = self._skip_nested_try(instructions, i)
                continue
            if op == "RERAISE":
                return i + 1
            if op in ("JUMP_FORWARD", "JUMP_ABSOLUTE"):
                dest = int(
                    instructions[i].argval
                    if instructions[i].argval is not None
                    else (instructions[i].arg or 0)
                )
                j = self._find_target_idx(instructions, dest)
                return j if j > i else i + 1
            if op == "RETURN_VALUE":
                return i + 1
            i += 1
        return n

    def _find_handler_end(self, instructions: List[Instruction], handler_start_idx: int) -> int:
        """First index at/after handler_start that terminates the handler sequence.

        A handler that returns ends at its ``RETURN_VALUE``, so the value it
        returns is part of the handler and has to be included; only the
        ``RETURN_VALUE`` that re-raises through no handler -- which follows the
        ``RERAISE`` -- is left out.
        """
        n = len(instructions)
        i = handler_start_idx
        while i < n:
            op = instructions[i].opname
            if op in ("SETUP_FINALLY", "SETUP_EXCEPT", "SETUP_WITH",
                            "SETUP_ASYNC_WITH"):
                i = self._skip_nested_try(instructions, i)
                continue
            if op in ("RERAISE", "JUMP_FORWARD", "JUMP_ABSOLUTE"):
                return i
            if op == "RETURN_VALUE":
                return i + 1
            i += 1
        return n

    def _collect_except_handler(
        self, instructions: List[Instruction], handler_start_idx: int
    ) -> Optional[Tuple[int, int, bool]]:
        """Locate the user-visible body of the first except handler.

        Returns ``(body_start, body_end, trailing_return)`` or ``None``.
        ``trailing_return`` marks handlers whose implicit ``as e`` finally performs the
        ``return`` of a value the body left on the stack.
        """
        if handler_start_idx >= len(instructions):
            return None
        raw_end = self._find_handler_end(instructions, handler_start_idx)
        # Implicit `as e` finally: SETUP_FINALLY right after the name binding.
        j = handler_start_idx
        as_e_setup_idx = None
        while j < raw_end:
            op = instructions[j].opname
            if op in ("DUP_TOP", "LOAD_NAME", "LOAD_GLOBAL", "LOAD_CONST",
                      "JUMP_IF_NOT_EXC_MATCH", "CHECK_EXC_MATCH", "POP_TOP"):
                j += 1
                continue
            if op == "STORE_FAST":
                j += 1
                if j < raw_end and instructions[j].opname == "POP_TOP":
                    j += 1
                if j < raw_end and instructions[j].opname in ("SETUP_FINALLY", "SETUP_EXCEPT"):
                    as_e_setup_idx = j
                break
            break
        if as_e_setup_idx is None:
            return self._trim_handler_tail(instructions, handler_start_idx, raw_end, False)
        setup_instr = instructions[as_e_setup_idx]
        target = int(setup_instr.argval if setup_instr.argval is not None else (setup_instr.arg or 0))
        inner_handler = self._find_target_idx(instructions, target)
        pop_idx = self._find_pop_block(instructions, as_e_setup_idx, target)
        if pop_idx > inner_handler:
            pop_idx = inner_handler
        # The normal-exit path between POP_BLOCK and the implicit finally carries the
        # handler's RETURN when the body left a value on the stack.
        trailing_return = any(
            instructions[k].opname == "RETURN_VALUE"
            for k in range(pop_idx + 1, min(inner_handler + 1, len(instructions)))
        )
        return self._trim_handler_tail(
            instructions, as_e_setup_idx + 1, pop_idx, trailing_return
        )

    def _trim_handler_tail(
        self, instructions: List[Instruction], start: int, end: int, trailing_return: bool
    ) -> Optional[Tuple[int, int, bool]]:
        """Drop trailing bookkeeping instructions from a handler body range."""
        tail_ops = ("RERAISE", "POP_EXCEPT", "ROT_FOUR", "ROT_TWO",
                    "CLEANUP_THROW", "CLEANUP_FINALLY")
        while end > start and instructions[end - 1].opname in tail_ops:
            end -= 1
        if end >= start + 3:
            a, b, c = instructions[end - 3], instructions[end - 2], instructions[end - 1]
            if (a.opname == "LOAD_CONST" and a.argval is None
                    and b.opname == "STORE_FAST" and c.opname == "DELETE_FAST"
                    and b.argval == c.argval):
                end -= 3
        while end > start and instructions[end - 1].opname in tail_ops:
            end -= 1
        if end <= start:
            return None
        return (start, end, trailing_return)

    def _detect_exception_type(
        self, instructions: List[Instruction], handler_start: int, body_start: int
    ) -> Optional[ast.expr]:
        # Typed-handler pattern: ``DUP_TOP``, the exception class (a global, a
        # module-level name or -- inside a function -- a local), then the match
        # test.  Requiring that third instruction keeps ``except X as e`` (whose
        # ``DUP_TOP; LOAD_FAST e; STORE_FAST e`` looks alike) from misreporting
        # the bound name as the exception type.
        limit = min(max(body_start, handler_start + 3), len(instructions))
        for i in range(handler_start, limit):
            if instructions[i].opname != "DUP_TOP" or i + 2 >= len(instructions):
                continue
            nxt = instructions[i + 1]
            if nxt.opname in ("LOAD_NAME", "LOAD_GLOBAL", "LOAD_FAST", "LOAD_DEREF") and (
                instructions[i + 2].opname
                in ("JUMP_IF_NOT_EXC_MATCH", "CHECK_EXC_MATCH")
            ):
                return ASTNode.make_Name(str(nxt.argval), ast.Load())
        return None

    def _detect_exception_name(
        self, instructions: List[Instruction], handler_start: int, body_start: int
    ) -> Optional[str]:
        limit = min(max(body_start, handler_start + 3), len(instructions))
        for i in range(handler_start, limit):
            if instructions[i].opname == "JUMP_IF_NOT_EXC_MATCH":
                for j in range(i + 1, min(i + 5, limit, len(instructions))):
                    if instructions[j].opname == "STORE_FAST":
                        return str(instructions[j].argval)
                break
        return None

    def _process_import_name(self, instr: Instruction, stack: List[ast.expr], stmts: List[ast.stmt]) -> int:
        if len(stack) < 2:
            return 1
        fromlist = stack.pop()
        level = stack.pop()
        mod_name = str(instr.argval)
        stack.append(ASTNode.make_Name(mod_name, ast.Load()))
        return 1

    def _make_constant(self, value: Any) -> ast.expr:
        if hasattr(value, "co_code"):
            return ast.Constant(value=value)
        if value is Ellipsis:
            return ast.Constant(value=Ellipsis)
        return ast.Constant(value=value)

    def _to_store_ctx(self, node: ast.expr):
        if isinstance(node, ast.Name):
            return ast.Name(id=node.id, ctx=ast.Store())
        if isinstance(node, ast.Attribute):
            return ast.Attribute(value=node.value, attr=node.attr, ctx=ast.Store())
        if isinstance(node, ast.Subscript):
            return ast.Subscript(value=node.value, slice=node.slice, ctx=ast.Store())
        return None

    def _statements_to_source(
        self,
        stmts: List[ast.stmt],
        indent_level: int,
        code=None,
        is_module: bool = False,
    ) -> str:
        try:
            self._fix_lineno(stmts)
            if indent_level > 0:
                module = ast.Module(body=stmts, type_ignores=[])
                ast.fix_missing_locations(module)
                source = ast.unparse(module)
                lines = source.split("\n")
                indented = [self._indent(indent_level) + l if l else "" for l in lines]
                return "\n".join(indented)
            else:
                module = ast.Module(body=stmts, type_ignores=[])
                ast.fix_missing_locations(module)
                return ast.unparse(module)
        except Exception:
            return self._fallback_source(stmts, indent_level, code, is_module)

    def _fix_lineno(self, nodes):
        count = [1]
        def set_lineno(node, count_ref):
            if isinstance(node, ast.AST):
                if not hasattr(node, "lineno") or getattr(node, "lineno", None) is None:
                    node.lineno = count_ref[0]
                    node.col_offset = 0
                else:
                    count_ref[0] = max(count_ref[0], node.lineno)
                count_ref[0] += 1
        for node in ast.walk(ast.Module(body=nodes, type_ignores=[])):
            set_lineno(node, count)

    def _fallback_source(self, stmts: List[ast.stmt], indent_level: int, code=None, is_module: bool = False) -> str:
        parts = []
        if code is not None and is_module:
            docstring = self._get_docstring(code)
            if docstring:
                parts.append(self._format_docstring(docstring, indent_level))
        for stmt in stmts:
            s = self._stmt_to_str(stmt, indent_level)
            if s:
                parts.append(s)
        return "\n".join(parts)

    def _get_docstring(self, code) -> Optional[str]:
        consts = getattr(code, "co_consts", ())
        if consts and isinstance(consts[0], str):
            return consts[0]
        return None

    def _format_docstring(self, doc: str, indent: int) -> str:
        indent_str = self._indent(indent)
        if "\n" in doc:
            return f'{indent_str}"""{doc}"""'
        return f'{indent_str}"""{doc}"""'

    def _stmt_to_str(self, stmt: ast.stmt, indent: int) -> str:
        ind = self._indent(indent)
        if isinstance(stmt, ast.Pass):
            return f"{ind}pass"
        if isinstance(stmt, ast.Expr):
            return f"{ind}{self._expr_to_str(stmt.value)}"
        if isinstance(stmt, ast.Assign):
            tgts = ", ".join(self._expr_to_str(t) for t in stmt.targets)
            return f"{ind}{tgts} = {self._expr_to_str(stmt.value)}"
        if isinstance(stmt, ast.AugAssign):
            op_map = {
                ast.Add: "+=", ast.Sub: "-=", ast.Mult: "*=", ast.Div: "/=",
                ast.FloorDiv: "//=", ast.Mod: "%=", ast.Pow: "**=",
                ast.LShift: "<<=", ast.RShift: ">>=", ast.BitAnd: "&=",
                ast.BitOr: "|=", ast.BitXor: "^=", ast.MatMult: "@=",
            }
            op_str = op_map.get(type(stmt.op), "??=")
            return f"{ind}{self._expr_to_str(stmt.target)} {op_str} {self._expr_to_str(stmt.value)}"
        if isinstance(stmt, ast.Return):
            if stmt.value is None:
                return f"{ind}return"
            return f"{ind}return {self._expr_to_str(stmt.value)}"
        if isinstance(stmt, ast.If):
            lines = [f"{ind}if {self._expr_to_str(stmt.test)}:"]
            if stmt.body:
                for b in stmt.body:
                    s = self._stmt_to_str(b, indent + 1)
                    if s:
                        lines.append(s)
            else:
                lines.append(f"{ind}    pass")
            if stmt.orelse:
                lines.append(f"{ind}else:")
                for b in stmt.orelse:
                    s = self._stmt_to_str(b, indent + 1)
                    if s:
                        lines.append(s)
            return "\n".join(lines)
        if isinstance(stmt, ast.For):
            lines = [f"{ind}for {self._expr_to_str(stmt.target)} in {self._expr_to_str(stmt.iter)}:"]
            if stmt.body:
                for b in stmt.body:
                    s = self._stmt_to_str(b, indent + 1)
                    if s:
                        lines.append(s)
            else:
                lines.append(f"{ind}    pass")
            return "\n".join(lines)
        if isinstance(stmt, ast.While):
            lines = [f"{ind}while {self._expr_to_str(stmt.test)}:"]
            if stmt.body:
                for b in stmt.body:
                    s = self._stmt_to_str(b, indent + 1)
                    if s:
                        lines.append(s)
            return "\n".join(lines)
        if isinstance(stmt, ast.FunctionDef):
            args_str = self._args_to_str(stmt.args)
            lines = [f"{ind}def {stmt.name}({args_str}):"]
            if stmt.body:
                for b in stmt.body:
                    s = self._stmt_to_str(b, indent + 1)
                    if s:
                        lines.append(s)
            else:
                lines.append(f"{ind}    pass")
            return "\n".join(lines)
        if isinstance(stmt, ast.ClassDef):
            lines = [f"{ind}class {stmt.name}:"]
            if stmt.body:
                for b in stmt.body:
                    s = self._stmt_to_str(b, indent + 1)
                    if s:
                        lines.append(s)
            return "\n".join(lines)
        if isinstance(stmt, ast.Import):
            names = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in stmt.names)
            return f"{ind}import {names}"
        if isinstance(stmt, ast.ImportFrom):
            names = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in stmt.names)
            mod = stmt.module or ""
            return f"{ind}from {'.' * getattr(stmt, 'level', 0)}{mod} import {names}"
        if isinstance(stmt, ast.Delete):
            targets = ", ".join(self._expr_to_str(t) for t in stmt.targets)
            return f"{ind}del {targets}"
        if isinstance(stmt, ast.Raise):
            if stmt.exc is None:
                return f"{ind}raise"
            return f"{ind}raise {self._expr_to_str(stmt.exc)}"
        if isinstance(stmt, ast.Try):
            lines = [f"{ind}try:"]
            for b in stmt.body:
                s = self._stmt_to_str(b, indent + 1)
                if s:
                    lines.append(s)
            for handler in stmt.handlers:
                exc_type = self._expr_to_str(handler.type) if handler.type else ""
                if exc_type:
                    lines.append(f"{ind}except {exc_type}:")
                else:
                    lines.append(f"{ind}except:")
                for b in handler.body:
                    s = self._stmt_to_str(b, indent + 2)
                    if s:
                        lines.append(s)
            if stmt.orelse:
                lines.append(f"{ind}else:")
                for b in stmt.orelse:
                    s = self._stmt_to_str(b, indent + 1)
                    if s:
                        lines.append(s)
            if stmt.finalbody:
                lines.append(f"{ind}finally:")
                for b in stmt.finalbody:
                    s = self._stmt_to_str(b, indent + 1)
                    if s:
                        lines.append(s)
            return "\n".join(lines)
        return f"{ind}# {type(stmt).__name__}"

    def _args_to_str(self, args: ast.arguments) -> str:
        parts = []
        for a in args.posonlyargs:
            parts.append(a.arg)
        if args.posonlyargs:
            parts.append("/")
        for a in args.args:
            parts.append(a.arg)
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")
        if args.kwonlyargs and not args.vararg:
            parts.append("*")
        for a in args.kwonlyargs:
            parts.append(a.arg)
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")
        return ", ".join(parts)

    def _expr_to_str(self, expr: ast.expr) -> str:
        if isinstance(expr, ast.Constant):
            if isinstance(expr.value, str):
                return repr(expr.value)
            if expr.value is None:
                return "None"
            if expr.value is True:
                return "True"
            if expr.value is False:
                return "False"
            if expr.value is Ellipsis:
                return "..."
            if hasattr(expr.value, "co_code"):
                return f"<code object {getattr(expr.value, 'co_name', '?')}>"
            return repr(expr.value)
        if isinstance(expr, ast.Name):
            return expr.id
        if isinstance(expr, ast.Attribute):
            return f"{self._expr_to_str(expr.value)}.{expr.attr}"
        if isinstance(expr, ast.Subscript):
            sl = expr.slice
            if isinstance(sl, ast.Index):
                sl_str = self._expr_to_str(sl.value)
            else:
                sl_str = self._expr_to_str(sl)
            return f"{self._expr_to_str(expr.value)}[{sl_str}]"
        if isinstance(expr, ast.BinOp):
            op_map = {
                ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
                ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**",
                ast.LShift: "<<", ast.RShift: ">>", ast.BitAnd: "&",
                ast.BitOr: "|", ast.BitXor: "^", ast.MatMult: "@",
            }
            return f"({self._expr_to_str(expr.left)} {op_map.get(type(expr.op), '?')} {self._expr_to_str(expr.right)})"
        if isinstance(expr, ast.UnaryOp):
            op_map = {ast.UAdd: "+", ast.USub: "-", ast.Not: "not ", ast.Invert: "~"}
            return f"{op_map.get(type(expr.op), '?')}{self._expr_to_str(expr.operand)}"
        if isinstance(expr, ast.Compare):
            ops_map = {
                ast.Lt: "<", ast.LtE: "<=", ast.Eq: "==", ast.NotEq: "!=",
                ast.Gt: ">", ast.GtE: ">=", ast.Is: "is", ast.IsNot: "is not",
                ast.In: "in", ast.NotIn: "not in",
            }
            left = self._expr_to_str(expr.left)
            parts = [left]
            for op, comp in zip(expr.ops, expr.comparators):
                parts.append(ops_map.get(type(op), "?"))
                parts.append(self._expr_to_str(comp))
            return "(" + " ".join(parts) + ")"
        if isinstance(expr, ast.Call):
            func = self._expr_to_str(expr.func)
            arg_strs = [self._expr_to_str(a) for a in expr.args]
            kw_strs = [f"{k.arg}={self._expr_to_str(k.value)}" if k.arg else f"**{self._expr_to_str(k.value)}" for k in expr.keywords]
            all_args = arg_strs + kw_strs
            return f"{func}({', '.join(all_args)})"
        if isinstance(expr, ast.Tuple):
            if not expr.elts:
                return "()"
            return "(" + ", ".join(self._expr_to_str(e) for e in expr.elts) + (",)" if len(expr.elts) == 1 else ")")
        if isinstance(expr, ast.List):
            return "[" + ", ".join(self._expr_to_str(e) for e in expr.elts) + "]"
        if isinstance(expr, ast.Set):
            return "{" + ", ".join(self._expr_to_str(e) for e in expr.elts) + "}"
        if isinstance(expr, ast.Dict):
            pairs = []
            for k, v in zip(expr.keys, expr.values):
                if k is None:
                    pairs.append(f"**{self._expr_to_str(v)}")
                else:
                    pairs.append(f"{self._expr_to_str(k)}: {self._expr_to_str(v)}")
            return "{" + ", ".join(pairs) + "}"
        if isinstance(expr, ast.JoinedStr):
            parts = []
            for v in expr.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value)
                elif isinstance(v, ast.FormattedValue):
                    inner = self._expr_to_str(v.value)
                    conv = ""
                    if v.conversion == ord("s"):
                        conv = "!s"
                    elif v.conversion == ord("r"):
                        conv = "!r"
                    elif v.conversion == ord("a"):
                        conv = "!a"
                    spec = ""
                    if v.format_spec:
                        spec = ":" + (v.format_spec.value if isinstance(v.format_spec, ast.Constant) and isinstance(v.format_spec.value, str) else "...")
                    parts.append("{" + inner + conv + spec + "}")
                else:
                    parts.append(self._expr_to_str(v))
            return 'f"' + "".join(parts) + '"'
        if isinstance(expr, ast.Lambda):
            args = self._args_to_str(expr.args)
            body = self._expr_to_str(expr.body)
            return f"(lambda {args}: {body})"
        if isinstance(expr, ast.Starred):
            return f"*{self._expr_to_str(expr.value)}"
        if isinstance(expr, ast.Yield):
            if expr.value is None:
                return "yield"
            return f"(yield {self._expr_to_str(expr.value)})"
        return f"<{type(expr).__name__}>"
