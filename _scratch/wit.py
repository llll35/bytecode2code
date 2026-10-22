def a(p):
    try:
        with open(p) as fh:
            g(fh)
        return True
    except ValueError:
        return False
