"""Version aware bytecode normalization.

This module is imported *inside the target interpreter*, so it may use that
interpreter's ``dis``/``opcode`` freely.  Its job is to flatten the bytecode
differences between CPython 3.9 and 3.14 into one common instruction record so
that the host can present a uniform view:

* super instructions (``LOAD_FAST_LOAD_FAST``, ``LOAD_FAST_BORROW`` ...) are
  expanded into the plain ``LOAD_FAST``/``STORE_FAST`` they stand for,
* ``BINARY_OP`` is split into the concrete numeric operation,
* the 3.11+ method call protocol (``PUSH_NULL`` / ``LOAD_ATTR`` flags) is
  tagged on the instruction itself,
* bookkeeping opcodes (``RESUME``, ``PRECALL``, ``CACHE`` ...) are dropped.
"""

import dis
import io
import re
import types

CO_VARARGS = 0x04
CO_VARKEYWORDS = 0x08
CO_GENERATOR = 0x20
CO_COROUTINE = 0x80
CO_ASYNC_GENERATOR = 0x200

#: Opcodes that carry no source level meaning.
DROPPED_OPS = frozenset((
    "RESUME", "CACHE", "NOP", "EXTENDED_ARG", "PRECALL", "NOT_TAKEN",
    "MAKE_CELL", "COPY_FREE_VARS", "RETURN_GENERATOR", "POP_ITER",
))

SUPER_FAST_RE = re.compile(r"^(?:LOAD|STORE)_FAST")
SUPER_SPLIT_RE = re.compile(r"_(?=(?:LOAD|STORE)_FAST)")


# --------------------------------------------------------------------------
# low level helpers
# --------------------------------------------------------------------------

def native_instructions(code):
    """``dis.get_instructions`` without inline caches, on any version."""
    try:
        return list(dis.get_instructions(code, show_caches=False))
    except TypeError:  # Python 3.9 / 3.10 have no inline caches
        return list(dis.get_instructions(code))


def _line_of(instruction):
    line = getattr(instruction, "line_no", None)
    if line is None:
        positions = getattr(instruction, "positions", None)
        if positions is not None:
            line = positions.lineno
    return line


def _intrinsic_name(arg, argrepr):
    if argrepr and not argrepr.startswith("<"):
        return argrepr
    table = getattr(dis, "_intrinsic_1_arg", None) or \
        getattr(dis, "_intrinsic_2_arg", None)
    if table is not None and arg is not None and arg < len(table):
        return table[arg]
    return None


def _split_fast_super(opname, argval):
    """Split a 3.13/3.14 local-variable super instruction into plain parts.

    ``"STORE_FAST_LOAD_FAST"`` becomes ``["STORE_FAST", "LOAD_FAST"]`` and
    ``"LOAD_FAST_BORROW_LOAD_FAST_BORROW"`` becomes two ``LOAD_FAST``.  Returns
    ``None`` for opcodes outside that family.
    """
    if not SUPER_FAST_RE.match(opname):
        return None
    if opname in ("LOAD_FAST", "STORE_FAST"):
        return [(opname, argval)]

    parts = [p.replace("_BORROW", "").replace("_AND_CLEAR", "")
              .replace("_CHECK", "")
             for p in SUPER_SPLIT_RE.split(opname)]
    if isinstance(argval, tuple) and all(isinstance(v, str) for v in argval):
        names = list(argval)
    else:
        names = [argval]
    if len(names) != len(parts):
        base = "STORE_FAST" if opname.startswith("STORE_FAST") else "LOAD_FAST"
        return [(base, argval)]
    return list(zip(parts, names))


def _is_method_attr(opname, argrepr):
    if opname == "LOAD_METHOD":
        return True
    if opname != "LOAD_ATTR" or not argrepr:
        return False
    return "NULL" in argrepr or "self" in argrepr


def _record(instruction, opname, arg, argrepr, value=None, extra=None):
    """Build one normalized instruction record.

    ``argval`` holds the *live* Python value; it is only sanitized when the
    record is serialised, so nested code objects stay reachable here.
    """
    if value is None:
        value = instruction.argval
    record = {
        "offset": instruction.offset,
        "op": opname,
        "arg": arg,
        "argval": value,
        "argrepr": argrepr,
        "line": _line_of(instruction),
        "is_jump_target": bool(getattr(instruction, "is_jump_target", False)),
    }
    if extra:
        record.update(extra)
    return record


def normalize_instructions(code):
    """Turn the native disassembly of *code* into normalized records."""
    raw = native_instructions(code)
    nb_ops = list(getattr(dis, "_nb_ops", None) or [])
    out = []
    last_const_tuple = None

    for instruction in raw:
        opname = instruction.opname
        arg = instruction.arg
        argval = instruction.argval
        argrepr = instruction.argrepr

        if opname in DROPPED_OPS:
            continue

        if opname == "RETURN_CONST":
            out.append(_record(instruction, "LOAD_CONST", arg, argrepr,
                               value=argval))
            out.append(_record(instruction, "RETURN_VALUE", None, None,
                               value=None))
            continue

        if opname == "LOAD_CONST" and isinstance(argval, tuple) and \
                all(isinstance(v, str) for v in argval):
            last_const_tuple = argval

        if opname == "BINARY_OP":
            name = nb_ops[arg][0] if arg is not None and arg < len(nb_ops) \
                else "BINARY_%s" % arg
            if name.startswith("NB_"):
                name = "BINARY_" + name[3:]
            out.append(_record(instruction, name, arg, argrepr, value=argval))
            continue

        super_parts = _split_fast_super(opname, argval)
        if super_parts is not None and super_parts[0][0] != opname:
            for name, value in super_parts:
                out.append(_record(instruction, name, None, value, value=value))
            continue

        extra = {}
        if opname in ("CALL", "CALL_KW", "CALL_FUNCTION_EX"):
            extra["nargs"] = arg
        if opname == "CALL_KW":
            extra["kwnames"] = list(last_const_tuple or ())
        if opname == "KW_NAMES":
            names = argval
            if not isinstance(names, tuple) and arg is not None and \
                    arg < len(code.co_consts):
                names = code.co_consts[arg]
            if isinstance(names, tuple):
                last_const_tuple = names
            extra["kwnames"] = list(names) if isinstance(names, tuple) else []
        if opname == "CALL_INTRINSIC_1":
            extra["intrinsic"] = _intrinsic_name(arg, argrepr)
        if _is_method_attr(opname, argrepr):
            extra["method"] = True
            opname = "LOAD_ATTR"
            argrepr = str(argval)

        out.append(_record(instruction, opname, arg, argrepr, value=argval,
                           extra=extra))

    return out


def safe(value, depth=0):
    """Best effort JSON friendly rendering of an arbitrary constant."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth > 4:
        return repr(value)
    if isinstance(value, types.CodeType):
        return {"code": getattr(value, "co_qualname", None) or value.co_name}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [safe(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {repr(safe(k, depth + 1)): safe(v, depth + 1)
                for k, v in value.items()}
    return repr(value)


def instruction_to_json(record):
    """Serialisable copy of a normalized instruction record."""
    clean = dict(record)
    clean["argval"] = safe(record["argval"])
    return clean


# --------------------------------------------------------------------------
# code object metadata
# --------------------------------------------------------------------------

def signature(code, is_module=False):
    """A ``def`` style parameter list for *code*."""
    if is_module:
        return ""
    names = code.co_varnames
    count = code.co_argcount
    only = getattr(code, "co_posonlyargcount", 0)
    kwonly = getattr(code, "co_kwonlyargcount", 0)
    has_varargs = bool(code.co_flags & CO_VARARGS)
    has_varkw = bool(code.co_flags & CO_VARKEYWORDS)

    parts = [name + "/" for name in names[:only]]
    parts += list(names[only:count])
    index = count + kwonly
    if kwonly:
        parts.append("*")
        parts += list(names[count:index])
    if has_varargs:
        parts.append("*%s" % names[index])
        index += 1
    if has_varkw:
        parts.append("**%s" % names[index])
    return ", ".join(parts)


def code_kind(code):
    """``"module"``, ``"lambda"``, ``"comprehension"`` or ``"function"``."""
    name = code.co_name
    if name == "<module>":
        return "module"
    if name == "<lambda>":
        return "lambda"
    if name.startswith("<") and name.endswith(">"):
        return "comprehension"
    return "function"


def function_flags(code):
    """Readable tags such as ``async`` / ``generator``."""
    tags = []
    if code.co_flags & CO_ASYNC_GENERATOR:
        tags.append("async-generator")
    elif code.co_flags & CO_COROUTINE:
        tags.append("async")
    elif code.co_flags & CO_GENERATOR:
        tags.append("generator")
    return tags


def nested_codes(code):
    """Direct child code objects, in ``co_consts`` order."""
    return [c for c in code.co_consts if isinstance(c, types.CodeType)]


def exception_entries(code):
    """``co_exceptiontable`` decoded into dicts (Python 3.11+ only)."""
    if not hasattr(code, "co_exceptiontable"):
        return []
    try:
        entries = dis.Bytecode(code).exception_entries
    except Exception:  # pragma: no cover - defensive
        return []
    return [
        {
            "start": start,
            "end": start + length,
            "target": target,
            "depth": depth,
            "lasti": bool(lasti),
        }
        for start, length, target, depth, lasti in entries
    ]


def build_ir(code, is_module=False):
    """Recursive, JSON friendly description of *code* and its children."""
    return {
        "name": code.co_name,
        "qualname": getattr(code, "co_qualname", code.co_name),
        "filename": code.co_filename,
        "firstlineno": code.co_firstlineno,
        "kind": code_kind(code),
        "signature": signature(code, is_module),
        "tags": function_flags(code),
        "flags": code.co_flags,
        "stacksize": code.co_stacksize,
        "argcount": code.co_argcount,
        "posonlyargcount": getattr(code, "co_posonlyargcount", 0),
        "kwonlyargcount": getattr(code, "co_kwonlyargcount", 0),
        "varnames": list(code.co_varnames),
        "names": list(code.co_names),
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
        "consts": [safe(c) for c in code.co_consts],
        "instructions": [instruction_to_json(i)
                         for i in normalize_instructions(code)],
        "exception_entries": exception_entries(code),
        "children": [
            {"name": child.co_name,
             "qualname": getattr(child, "co_qualname", child.co_name),
             "ir": build_ir(child)}
            for child in nested_codes(code)
        ],
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def render_disassembly(code):
    """Native ``dis`` output, produced by the target interpreter itself."""
    buffer = io.StringIO()
    dis.dis(code, file=buffer)
    return buffer.getvalue()


def render_skeleton(code, version=""):
    """Render *code* as a readable, normalized pseudo source listing.

    Nested functions and classes become real ``def``/``class`` blocks so the
    module structure survives, even though statement level reconstruction is
    not attempted for the 3.11+ calling conventions.
    """
    lines = []
    if code_kind(code) == "module":
        lines.append("# normalized bytecode skeleton (CPython %s)" % (version or "?"))
        lines.append("# source file: %s" % code.co_filename)
        lines.append("")
        _render_body(code, 0, lines)
    else:
        _render_function(code, 0, lines)
    return "\n".join(lines) + "\n"


def _indent(level):
    return "    " * level


def _render_function(code, level, lines):
    tags = function_flags(code)
    is_async = "async" in tags or "async-generator" in tags
    kind = code_kind(code)
    if kind == "lambda":
        header = "lambda %s: ..." % signature(code)
    else:
        header = "%sdef %s(%s):" % ("async " if is_async else "",
                                     code.co_name, signature(code))
    lines.append("%s%s" % (_indent(level), header))
    _render_body(code, level + 1, lines)


def _render_body(code, level, lines):
    instructions = normalize_instructions(code)
    labels = {i["offset"] for i in instructions if i.get("is_jump_target")}
    body = []
    last_line = None
    index = 0
    total = len(instructions)

    while index < total:
        record = instructions[index]

        if record["offset"] in labels:
            body.append("%sL%d:" % (_indent(level), record["offset"]))

        value = record["argval"]
        if isinstance(value, types.CodeType) and index + 1 < total and \
                instructions[index + 1]["op"] == "MAKE_FUNCTION":
            is_class = _is_class_body(instructions, index)
            index = _skip_definition(instructions, index)
            if is_class:
                body.append("%sclass %s:" % (_indent(level), value.co_name))
                _render_body(value, level + 1, body)
            else:
                _render_function(value, level, body)
            body.append("")
            last_line = None
            continue

        if record["line"] and record["line"] != last_line:
            body.append("%s# line %d" % (_indent(level), record["line"]))
            last_line = record["line"]

        body.append("%s%-6s %-28s %s" % (_indent(level), record["offset"],
                                         record["op"], _render_arg(record)))
        index += 1

    lines.extend(body)


def _render_arg(record):
    parts = []
    if record.get("method"):
        parts.append("[method]")
    if record.get("kwnames"):
        parts.append("kw=%s" % (record["kwnames"],))
    if record.get("intrinsic"):
        parts.append("intrinsic=%s" % record["intrinsic"])
    if record["argrepr"]:
        parts.append(str(record["argrepr"]))
    return " ".join(parts)


def _is_class_body(instructions, index):
    """A class body is built with ``LOAD_BUILD_CLASS`` right before its code."""
    for back in range(index - 1, max(-1, index - 4), -1):
        op = instructions[back]["op"]
        if op == "LOAD_BUILD_CLASS":
            return True
        if op in ("PUSH_NULL", "LOAD_CONST", "RESUME", "NOP"):
            continue
        return False
    return False


def _skip_definition(instructions, index):
    """Index just past the ``MAKE_FUNCTION``/call/store sequence."""
    index += 2  # skip LOAD_CONST <code> and MAKE_FUNCTION
    total = len(instructions)
    while index < total and instructions[index]["op"] in (
            "PRECALL", "KW_NAMES", "CALL", "CALL_KW", "CALL_FUNCTION_EX"):
        index += 1
    if index < total and instructions[index]["op"] in (
            "STORE_NAME", "STORE_FAST", "STORE_ATTR", "STORE_GLOBAL",
            "STORE_DEREF", "POP_TOP"):
        index += 1
    return index
