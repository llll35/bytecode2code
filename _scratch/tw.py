def f(p):
    with open(p) as fh:
        try:
            return fh.read()
        except OSError:
            return ''
