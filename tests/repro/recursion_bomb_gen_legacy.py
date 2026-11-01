# gen.py
N = 700
rows = []
rows.append("def bomb():")
rows.append("    x = 1")

# 从内向外，先放最里面一行
# level: 缩进层级，1 = 4空格
# 先把最内层语句放好
stack = [("x += 1", 1)]

for i in range(N):
    body_str, lv = stack.pop()
    new_lv = lv
    prefix = "    " * new_lv
    rows.append(f"{prefix}try:")
    # 主体，再往里多一级缩进
    rows.append(f"{prefix}    {body_str}")
    rows.append(f"{prefix}finally:")
    rows.append(f"{prefix}    if x > 9999:")
    rows.append(f"{prefix}        return {i}")
    # 下一轮，把整个try块当成body，层级不变
    stack.append( ("", new_lv) )

rows.append("    return x")

# 写入文件
with open("recursion_bomb_gen.py", "w", encoding="utf-8") as f:
    f.write("\n".join(rows))

print("生成完成")