def f(p):
    try:
        with open(p) as handle:
            return handle
    except OSError:
        return None
