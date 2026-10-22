def f(a, items):
    with a as x:
        for i in items:
            if i:
                break
        return x
