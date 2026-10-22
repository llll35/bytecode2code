"""Trace the value stack of a function for a few concrete inputs."""

import dis


def trace(code, env, name):
    instrs = list(dis.get_instructions(code))
    off2idx = {ins.offset: i for i, ins in enumerate(instrs)}
    stack = []
    pc = 0
    steps = 0

    def show(v):
        if isinstance(v, list):
            return "[%s]" % ", ".join(show(x) for x in v)
        return repr(v)

    while pc < len(instrs) and steps < 500:
        ins = instrs[pc]
        op = ins.opname
        steps += 1

        if op == "LOAD_CONST":
            stack.append(ins.argval)
            nxt = pc + 1
        elif op in ("LOAD_FAST", "LOAD_GLOBAL", "LOAD_DEREF", "LOAD_NAME"):
            stack.append(env[ins.argval])
            nxt = pc + 1
        elif op == "DUP_TOP":
            stack.append(stack[-1])
            nxt = pc + 1
        elif op == "ROT_TWO":
            stack[-1], stack[-2] = stack[-2], stack[-1]
            nxt = pc + 1
        elif op == "ROT_THREE":
            stack[-3:] = [stack[-1], stack[-3], stack[-2]]
            nxt = pc + 1
        elif op == "COMPARE_OP":
            b = stack.pop()
            a = stack.pop()
            stack.append(a < b)
            nxt = pc + 1
        elif op == "POP_TOP":
            stack.pop()
            nxt = pc + 1
        elif op == "JUMP_IF_FALSE_OR_POP":
            if stack[-1]:
                stack.pop()
                nxt = pc + 1
            else:
                nxt = off2idx[ins.argval]
        elif op == "POP_JUMP_IF_FALSE":
            cond = stack.pop()
            nxt = pc + 1 if cond else off2idx[ins.argval]
        elif op == "JUMP_IF_TRUE_OR_POP":
            if stack[-1]:
                nxt = off2idx[ins.argval]
            else:
                stack.pop()
                nxt = pc + 1
        elif op == "POP_JUMP_IF_TRUE":
            cond = stack.pop()
            nxt = off2idx[ins.argval] if cond else pc + 1
        elif op in ("JUMP_FORWARD", "JUMP_ABSOLUTE", "JUMP_BACKWARD"):
            nxt = off2idx[ins.argval]
        elif op in ("RETURN_VALUE", "RETURN_CONST"):
            value = stack.pop() if stack else None
            print("  %4d %-22s ret=%r  leftover=%s"
                  % (ins.offset, op, value, show(stack)))
            return
        else:
            print("  %4d %-22s ?? unhandled" % (ins.offset, op))
            return

        print("  %4d %-22s stack=%s" % (ins.offset, op, show(stack)))
        pc = nxt


def probe(x):
    return 0 < x <= 10 and x != 5 or x == -1


for value in (-1, 5, 7):
    print("=== x = %r ===" % value)
    trace(probe.__code__, {"x": value}, "probe")
    print()
