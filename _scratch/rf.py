def f(p):
    try:
        g(p)
    except ValueError:
        return False
