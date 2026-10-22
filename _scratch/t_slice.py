import dis
SRC = (
    "def a(s, i, j):\n"
    "    return s[i:j]\n"
    "def b(s, i, j, k):\n"
    "    return s[i:j:k]\n"
    "def c(s, i, j, v):\n"
    "    s[i:j] = v\n"
    "def d(s, i):\n"
    "    return s[i:]\n"
    "def e(s, j):\n"
    "    return s[:j]\n"
)
code = compile(SRC, "t.py", "exec")
for c in code.co_consts:
    if hasattr(c, "co_name"):
        print("###", c.co_name)
        dis.dis(c)
