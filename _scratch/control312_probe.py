"""Runtime experiments for the 3.12+ control-flow layout."""
import importlib
import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
package = "py%d%dDecompiler" % sys.version_info[:2]
mod = importlib.import_module(package + ".decomp311")
base = importlib.import_module(package + ".decompiler").Decompiler
flags = set(os.environ.get("PATCHES", "").split(","))
if "skip" in flags:
    import inspect
    import textwrap
    source = textwrap.dedent(inspect.getsource(base._emit_statements))
    begin = source.index('        # ``while cond:``')
    split = source.index('        # Skip instructions that form')
    finish = source.index('        instr = instructions[i]')
    source = source[:begin] + source[split:finish] + source[begin:split] + source[finish:]
    namespace = dict(importlib.import_module(package + '.decompiler').__dict__)
    exec(source, namespace)
    base._emit_statements = namespace['_emit_statements']
if "trace" in flags:
    def trace(frame, event, arg):
        if frame.f_code.co_name in ('_emit_except_clause', '_parse_handler_body', '_process_with') and event in ('call', 'return'):
            print(event, frame.f_code.co_name, {k: frame.f_locals.get(k) for k in ('start', 'end', 'body_start', 'body_end', 'idx')}, 'handled', frame.f_locals['self']._handled_ranges, 'result', arg)
        return trace
    sys.settrace(trace)
if "common" in flags:
    old_normalise = mod.Rewriter._normalise_raw
    def normalise(self, raw_list):
        raw_list = [raw._replace(opname='LOAD_CONST', arg=None, argval=None) if raw.opname == 'LOAD_COMMON_CONSTANT' and mod._common_constant(raw.arg) is None else raw for raw in raw_list]
        return old_normalise(self, raw_list)
    mod.Rewriter._normalise_raw = normalise
if "tail" in flags:
    old_save = mod.Rewriter._save_tail_for_merge
    def save(self, tail_start, merge_offset):
        old_save(self, tail_start, merge_offset)
        tails = getattr(self, '_tails_at_merge', {})
        tail = tails.get(merge_offset)
        if not tail:
            return
        for entry in mod._exception_entries(self.code):
            if entry.end != tail_start:
                continue
            index = self._offset_index(entry.target)
            if index is None or not self._is_finally_handler(self.raw, index):
                continue
            body = []
            for ins in self.raw[index + 1:]:
                if ins.opname == 'RERAISE':
                    if body and len(body) < len(tail) and all(a.opname == b.opname and a.argval == b.argval for a, b in zip(body, tail)):
                        tails[merge_offset] = tail[len(body):]
                    break
                if ins.opname in mod._JUMP_OPS or ins.opname.startswith('POP_JUMP') or ins.opname in ('RETURN_VALUE','RETURN_CONST'):
                    break
                body.append(ins)
    mod.Rewriter._save_tail_for_merge = save
if "with" in flags:
    mod.Decompiler311._process_with = base._process_with
if "handlers" in flags:
    old_handlers = mod.Decompiler311._parse_except_handlers
    def handlers(self, code, instructions, handler_start_idx, try_end_idx=None):
        result = old_handlers(self, code, instructions, handler_start_idx, try_end_idx)
        if result is not None:
            self._handled_ranges.append((handler_start_idx, result[2]))
        return result
    mod.Decompiler311._parse_except_handlers = handlers
    old_else = mod.Decompiler311._recover_else_clause
    def recover(self, code, instructions, try_end_idx, handler_start_idx, post):
        for ins in instructions[try_end_idx + 1:handler_start_idx]:
            if ins.opname in ('JUMP_FORWARD','JUMP_ABSOLUTE') and ins.argval < ins.offset:
                return []
        return old_else(self, code, instructions, try_end_idx, handler_start_idx, post)
    mod.Decompiler311._recover_else_clause = recover
if "end" in flags:
    mod.Decompiler311._handler_end = base._handler_end
if "heads" in flags:
    original_run = mod.Rewriter.run
    def run(self):
        out = original_run(self)
        offsets = {i.offset for i in out}
        targets = {}
        for head in self._handler_heads & self._drops:
            if head in offsets:
                continue
            for ins in out:
                if ins.offset > head:
                    targets[head] = ins.offset
                    break
        for ins in out:
            if ins.opname == "SETUP_FINALLY" and ins.argval in targets:
                ins.argval = targets[ins.argval]
                ins.argrepr = str(ins.argval)
        return out
    mod.Rewriter.run = run
os.environ["FLOW VERBOSE"] = "-v"
runpy.run_path(os.path.join(os.path.dirname(__file__), "flow.py"), run_name="__main__")
