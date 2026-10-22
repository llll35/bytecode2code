import dis

def sim(src):
    code = compile(src, "<s>", "exec").co_consts[0]
    print("=== ", src.strip().replace("\n", " | "))
    st = []
    for ins in dis.get_instructions(code):
        op = ins.opname
        if op in ("LOAD_CONST", "LOAD_FAST", "LOAD_GLOBAL", "LOAD_NAME", "LOAD_DEREF"):
            st.append(ins.argrepr)
        elif op == "DUP_TOP":
            st.append(st[-1] + "*")
        elif op == "DUP_TOP_TWO":
            st.extend([st[-2] + "*", st[-1] + "*"])
        elif op == "ROT_TWO":
            st[-1], st[-2] = st[-2], st[-1]
        elif op == "ROT_THREE":
            st[-1], st[-2], st[-3] = st[-2], st[-3], st[-1]
        elif op in ("COMPARE_OP", "IS_OP", "CONTAINS_OP", "BINARY_ADD", "BINARY_MULTIPLY"):
            b = st.pop(); a = st.pop()
            st.append("(%s %s)" % (a, ins.argrepr if op == "COMPARE_OP" else op))
        elif op in ("POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE", "JUMP_IF_FALSE_OR_POP", "JUMP_IF_TRUE_OR_POP"):
            print("%4s %-22s %-14s stack=%s" % (ins.offset, op, "->%s" % ins.argval, st))
            if op.startswith("JUMP_IF"):
                pass
            else:
                st.pop()
            continue
        elif op in ("RETURN_VALUE",):
            print("%4s %-22s %-14s stack=%s" % (ins.offset, op, "", st))
            st.pop()
            continue
        else:
            print("%4s %-22s %-14s stack=%s" % (ins.offset, op, "", st))
            continue
        print("%4s %-22s %-14s stack=%s" % (ins.offset, op, "", st))

sim("def f(a,b,c):\n return 0 < a < b < c\n")
sim("def f(a,b):\n x = 0 < a < b\n return x\n")
sim("def f(x):\n return 0 < x <= 10 and x != 5 or x == -1\n")
sim("def f(a,b):\n return a and 0 < a < 10\n")
sim("def f(a,b,c):\n return (0 < a < b) and c\n")
