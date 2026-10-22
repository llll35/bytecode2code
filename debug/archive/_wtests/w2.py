def f(a):
    with a as x:
        try:
            pass
        except ValueError:
            pass
