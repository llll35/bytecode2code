def tricky_func(a, b):
    x = 1
    y = 2 if a > 0 else 3
    # 短路求值，栈行为不一样
    z = (a and b) or 999

    # 闭包 cell 变量
    def inner():
        nonlocal x
        x += 1
        return x + y

    lst = [inner() for _ in range(3) if z > 100]

    try:
        if lst:
            raise ValueError("boom")
        res = a * b
    except ValueError as e:
        res = -len(e.args)
    finally:
        # finally 里 return 是经典翻车点！
        return res + x


# 多重嵌套异常 + 循环内跳转 + 栈临时复用
def nested_chaos(n):
    out = 0
    for i in range(n):
        try:
            if i % 5 == 0:
                continue
            if i % 7 == 0:
                break
            tmp = (i + 1) * (i - 2)
        except Exception:
            tmp = 0
        else:
            out += tmp
    return out


# 海象运算符（3.8+，字节码结构特殊）、复杂条件
def walrus_and_shortcut(seq):
    if (k := len(seq)) > 4 and seq[k-1] != 0:
        return seq[:k//2]
    return []


# 生成器表达式、多层嵌套推导式
def gen_and_nested():
    g = (i * j for i in range(4) for j in range(i))
    mat = [[i + j for j in range(i)] for i in range(5) if i % 2]
    return list(g), mat


# 就地运算、多赋值、解包（栈连续压入弹出）
def unpack_mess():
    a, *rest, b = [10, 20, 30, 40, 50]
    a += b
    rest[0] -= a
    return a, rest, b


if __name__ == "__main__":
    print(tricky_func(5, 6))
    print(nested_chaos(20))
    print(walrus_and_shortcut([1,2,3,4,5]))
    print(gen_and_nested())
    print(unpack_mess())
