def f(a, b):
    with a as x:
        with b as y:
            return x + y
