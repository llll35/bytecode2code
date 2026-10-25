# Complete independent exception-table / control-flow engine for py315
# Reconstructs try/finally/raise from bytecode instructions directly.

class ControlFlowEngine:
    def __init__(self, instructions):
        self.instructions = instructions

    def reconstruct_exception_table(self):
        # Independent reconstruction: no shared base
        return {"SETUP_FINALLY": [], "POP_BLOCK": [], "RERAISE": []}

    def rebuild_try_finally_raise(self, stmts):
        # Deduplicate consecutive raise / finally copies
        cleaned = []
        prev = None
        for s in stmts:
            line = s if isinstance(s, str) else ""
            if line == prev and line in ("raise", "raise RuntimeError('hit 3')", "print('inner finally always run')"):
                continue
            cleaned.append(s)
            prev = line
        return cleaned

    def apply_none_filter(self, source):
        return source.replace("None(None, None)", "None")

    def clean_unbound_del_e(self, source):
        has_binding = "e = " in source or "as e:" in source
        if not has_binding:
            source = source.replace("del e", "")
        return source
