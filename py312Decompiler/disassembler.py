import dis
import inspect
import opcode
from dataclasses import dataclass, field
from typing import List, Optional, Any, Tuple

#: ``dis.get_instructions`` grew a ``show_caches`` keyword in 3.11 and the
#: default flipped to showing inline caches in 3.13, so the call has to be
#: shaped per interpreter.  Resolved once instead of on every code object.
_GET_INSTRUCTIONS_KWARGS = (
    {"show_caches": False}
    if "show_caches" in inspect.signature(dis.get_instructions).parameters
    else {}
)


def _line_of(instr: dis.Instruction) -> Optional[int]:
    """Source line an instruction belongs to.

    ``dis.Instruction.starts_line`` was deprecated in 3.12 and removed in
    3.13, where the number moved to ``positions.lineno``.
    """
    line = getattr(instr, "starts_line", None)
    if line is not None:
        return line
    positions = getattr(instr, "positions", None)
    if positions is not None:
        return positions.lineno
    return None


@dataclass
class Instruction:
    offset: int
    opcode: int
    opname: str
    arg: Optional[int]
    argval: Any
    argrepr: str
    line_no: Optional[int] = None
    is_jump_target: bool = False

    def __str__(self):
        parts = []
        parts.append(f"{self.offset:4d}")
        if self.line_no is not None:
            parts.append(f"{self.line_no:3d}")
        else:
            parts.append("   ")
        parts.append(f">>" if self.is_jump_target else "  ")
        parts.append(f"{self.opname:25s}")
        if self.arg is not None:
            parts.append(f"{self.arg:5d}")
            parts.append(f"({self.argrepr})")
        return " ".join(parts)


class Disassembler:
    def __init__(self):
        self._opmap = {v: k for k, v in opcode.opmap.items()}
        self._hasname = set(opcode.hasname)
        self._hasconst = set(opcode.hasconst)
        self._hasjrel = set(opcode.hasjrel)
        self._hasjabs = set(opcode.hasjabs)
        self._haslocal = set(opcode.haslocal)
        self._hascompare = set(opcode.hascompare)
        self._hasfree = set(opcode.hasfree)

    def _get_arg(self, instr: dis.Instruction) -> Optional[int]:
        return instr.arg

    def _get_argval(self, instr: dis.Instruction, code) -> Any:
        op = instr.opcode
        arg = instr.arg
        if arg is None:
            return None
        # For jump instructions, ensure argval uses the combined (extended) arg
        if op in self._hasjrel or op in self._hasjabs:
            if instr.argval is not None:
                return int(instr.argval)
            return arg
        # ``dis`` already dereferenced the operand against the right tables for
        # the running interpreter, and the encoding is not stable across
        # releases: 3.11 packs a flag bit into the low bit of ``LOAD_GLOBAL``'s
        # oparg, 3.12 adds the same for ``LOAD_ATTR``, ``LOAD_SUPER_ATTR`` packs
        # two, and 3.11+ resolves locals and free variables through
        # ``co_localsplusnames``.  Re-deriving any of that by hand reads the
        # wrong name or indexes off the end of ``co_names``, so take the value
        # ``dis`` reports.
        if (
            op in self._hasconst
            or op in self._hasname
            or op in self._haslocal
            or op in self._hasfree
            or op in self._hascompare
        ):
            return instr.argval
        return arg

    def _get_argrepr(self, instr: dis.Instruction, code, argval) -> str:
        op = instr.opcode
        if instr.arg is None:
            return ""
        if op in self._hasconst:
            if isinstance(argval, str):
                return repr(argval)
            if hasattr(argval, "co_code"):
                return f"<code object {getattr(argval, 'co_name', '?')}>"
            return repr(argval)
        if op in self._hasname or op in self._haslocal:
            return str(argval)
        if op in self._hascompare:
            return str(argval)
        if op in self._hasfree:
            return str(argval)
        if op in self._hasjrel or op in self._hasjabs:
            return f"to {argval}"
        return str(instr.arg)

    def _merge_extended_args(self, instr_list: list) -> list:
        """Merge EXTENDED_ARG into the following instruction's arg."""
        merged: List[dis.Instruction] = []
        i = 0
        while i < len(instr_list):
            instr = instr_list[i]
            if instr.opcode == opcode.EXTENDED_ARG:
                j = i + 1
                while j < len(instr_list) and instr_list[j].opcode == opcode.EXTENDED_ARG:
                    j += 1
                if j < len(instr_list):
                    next_instr = instr_list[j]
                    # Combine all EXTENDED_ARG values
                    ext_val = instr.arg or 0
                    k = i + 1
                    while k < j:
                        ext_val = (ext_val << 8) | (instr_list[k].arg or 0)
                        k += 1
                    combined_arg = (ext_val << 8) | (next_instr.arg if next_instr.arg is not None else 0)
                    new_instr = next_instr._replace(arg=combined_arg)
                    merged.append(new_instr)
                    i = j + 1
                    continue
            merged.append(instr)
            i += 1
        return merged

    def disassemble(self, code, show_lineno: bool = True) -> List[Instruction]:
        instructions: List[Instruction] = []
        jump_targets: set = set()
        raw_instr_list = list(dis.get_instructions(code, **_GET_INSTRUCTIONS_KWARGS))
        # Merge EXTENDED_ARG into following instructions
        instr_list = self._merge_extended_args(raw_instr_list)
        for instr in instr_list:
            if instr.opcode in self._hasjrel or instr.opcode in self._hasjabs:
                if instr.argval is not None:
                    jump_targets.add(int(instr.argval))
            elif instr.is_jump_target:
                # 3.11+ also marks the handler and cleanup targets that come
                # from co_exceptiontable, which no jump instruction points at.
                jump_targets.add(instr.offset)
        for instr in instr_list:
            op = instr.opcode
            arg = self._get_arg(instr)
            argval = self._get_argval(instr, code)
            argrepr = self._get_argrepr(instr, code, argval)
            line_no = _line_of(instr) if show_lineno else None
            is_jump = instr.offset in jump_targets
            instructions.append(Instruction(
                offset=instr.offset,
                opcode=op,
                opname=instr.opname,
                arg=arg,
                argval=argval,
                argrepr=argrepr,
                line_no=line_no,
                is_jump_target=is_jump,
            ))
        return instructions

    def disassemble_to_str(self, code, show_header: bool = True, show_lineno: bool = True) -> str:
        lines = []
        if show_header:
            lines.append(f"Disassembly of {getattr(code, 'co_name', '<code>')}:")
            co_args = getattr(code, "co_argcount", 0)
            co_kwonly = getattr(code, "co_kwonlyargcount", 0)
            co_locals = len(getattr(code, "co_varnames", []))
            lines.append(f"  co_argcount: {co_args}, co_kwonlyargcount: {co_kwonly}, co_nlocals: {co_locals}")
            lines.append(f"  co_flags: {getattr(code, 'co_flags', 0):#x}")
            lines.append(f"  co_firstlineno: {getattr(code, 'co_firstlineno', None)}")
            varnames = getattr(code, "co_varnames", ())
            if varnames:
                lines.append(f"  co_varnames: {varnames!r}")
            names = getattr(code, "co_names", ())
            if names:
                lines.append(f"  co_names: {names!r}")
            consts = getattr(code, "co_consts", ())
            if consts:
                repr_consts = []
                for c in consts:
                    if hasattr(c, "co_code"):
                        repr_consts.append(f"<code {getattr(c, 'co_name', '?')}>")
                    else:
                        repr_consts.append(repr(c))
                lines.append(f"  co_consts: ({', '.join(repr_consts)},)")
        lines.append("")
        lines.append(f"{'OFFSET':>6s} {'LN':>3s} {'LABEL':5s} {'OPCODE':25s} {'ARG':>5s} REPR")
        lines.append("-" * 70)
        for instr in self.disassemble(code, show_lineno=show_lineno):
            lines.append(str(instr))
        return "\n".join(lines)
