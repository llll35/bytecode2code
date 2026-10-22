def f(p):
    while True:
        with open(p) as fh:
            if fh.read():
                break
    return 1
