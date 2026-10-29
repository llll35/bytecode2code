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
                raise
            finally:
                print("inner finally always run")
    except ValueError as ve:
        print(f"outer value error: {ve}")
        return -1
    except Exception as ee:
        print(f"outer other: {ee}")
    finally:
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