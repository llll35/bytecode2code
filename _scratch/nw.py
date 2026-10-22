def f(a, b):
    try:
        with open(a) as x, open(b) as y:
            return x.read() + y.read()
    except OSError:
        return ''
