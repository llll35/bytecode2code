"""Experiment with synthetic close addresses and conditional handler exits."""
import importlib
import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
pkg = 'py%d%dDecompiler' % sys.version_info[:2]
mod = importlib.import_module(pkg + '.decomp311')
flags = set(sys.argv[1:])

if 'handler' in flags:
    mod.Decompiler311._handler_end = mod.Decompiler310._handler_end

if 'heads' in flags:
    original_run = mod.Rewriter.run

    def run(self):
        out = original_run(self)
        offsets = {ins.offset for ins in out}
        for head in sorted(self._handler_heads):
            if head in offsets:
                continue
            for ins in out:
                if ins.offset > head:
                    ins.offset = head
                    offsets.add(head)
                    break
        return out

    mod.Rewriter.run = run

if 'close' in flags:
    original = mod.Rewriter._close_offset

    def close_offset(self, index):
        raw = self.raw[index]
        end = self.try_closes.get(raw.offset)
        if end is not None and end not in self._handler_heads:
            stubs = self._unwind_stubs(mod._exception_entries(self.code))
            between = [r for r in self.raw[index + 1:] if r.offset < end]
            if between and any(lo <= between[0].offset < hi for lo, hi in stubs) and all(
                    r.offset in self._drops or r.opname in mod._SILENT
                    or any(lo <= r.offset < hi for lo, hi in stubs)
                    for r in between):
                return end
        return original(self, index)

    mod.Rewriter._close_offset = close_offset

if 'regions' in flags:
    from tests.cases import FLOW_PROBES
    cfg = importlib.import_module(pkg + '.cfg_flow')
    code = compile(FLOW_PROBES['nested_finally_reraise'], 'probe.py', 'exec').co_consts[0]
    instructions = mod.Rewriter(code).run()
    for r in cfg.ExceptionAnalyzer(instructions, cfg.build_cfg(instructions)).regions():
        print('region', r.setup_index, 'body', r.body_start, r.body_end,
              'pops', r.body_pops, 'exits', r.exit_pops, 'handlers', r.handlers)
else:
    sys.argv = ['flow.py']
    if 'verbose' in flags:
        os.environ['FLOW VERBOSE'] = '-v'
    runpy.run_path(os.path.join(os.path.dirname(__file__), 'flow.py'), run_name='__main__')
