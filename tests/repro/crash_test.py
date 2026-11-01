def chaos_func(a, b):
    # 第一层嵌套
    try:
        if a < 0:
            raise ValueError("a negative")
        for idx in range(a):
            # with + 内层try
            with open("junk.txt", "w") as f:
                f.write(f"{idx}\n")
                try:
                    if idx == 2:
                        raise RuntimeError("hit 2")
                    elif idx == 5:
                        raise OSError("io bad")
                except RuntimeError as re:
                    print(f"catch runtime: {re}")
                    # except内部裸raise（真的raise，要保留）
                    raise
                except OSError as oe:
                    print(f"catch os: {oe}")
                    if b > 100:
                        # except里面直接return
                        return -99
                    raise
                finally:
                    print("inner finally A")
                    if idx == 3:
                        # finally里面return，这个是3.11字节码最难还原的一类
                        return 111
        # 循环结束后第二个try
        try:
            if b == 0:
                raise ZeroDivisionError("b zero")
        except ZeroDivisionError as ze:
            print(f"zero err: {ze}")
            raise
        finally:
            print("mid finally B")
            if a > 10:
                return 222
    except ValueError as ve:
        print(f"outer value err: {ve}")
        if b < 0:
            return -1
        raise
    except Exception as ge:
        print(f"outer any err: {ge}")
    finally:
        print("outer finally C")
        if a + b > 20:
            return 999
    # 正常返回点
    return 0


def deep_nested():
    # 四层连续try嵌套，只在最内层raise，逐层finally+选择性捕获
    try:
        try:
            try:
                try:
                    raise FileNotFoundError("deep lost")
                finally:
                    print("lv4 finally")
            except FileNotFoundError as fe:
                print("lv3 catch file")
                raise
            finally:
                print("lv3 finally")
        except OSError as ose:
            print("lv2 catch os")
        finally:
            print("lv2 finally")
    finally:
        print("lv1 finally")


def mix_with_and_raise():
    # 多个with嵌套，with内部抛异常，交叉finally
    try:
        with open("a.txt") as fa, open("b.txt") as fb:
            raise SyntaxError("fake syntax")
    except SyntaxError as se:
        print("catch syntax", se)
    finally:
        print("with outer finally")


if __name__ == "__main__":
    chaos_func(-3, 5)
    chaos_func(6, 200)
    deep_nested()
    mix_with_and_raise()