# test_break_b2c.py
def demo_bad_case(x):
    try:
        if x < 0:
            raise ValueError("less than zero")
        for i in range(x):
            try:
                with open("tmp.txt", "w") as f:
                    f.write(str(i))
                    if i == 3:
                        raise RuntimeError("hit 3")
            except RuntimeError as e:
                print(f"inner catch: {e}")
                raise  # 这里会生成 RERAISE，是 bytecode2code 最头疼的
            finally:
                print("inner finally always run")
    except ValueError as ve:
        print(f"outer value error: {ve}")
        return -1
    except Exception as ee:
        print(f"outer other: {ee}")
    finally:
        # 经典大坑：finally 里面 return，会吞掉上层异常，3.9字节码栈很难还原
        if x > 100:
            return 999
        print("outer finally")
    return 0


def nested_try_chain():
    try:
        try:
            try:
                raise OSError("deep error")
            except OSError:
                raise IOError("wrap os error")
        except IOError:
            raise
    except Exception as e:
        print("caught deep wrap", e)


if __name__ == "__main__":
    demo_bad_case(-5)
    nested_try_chain()