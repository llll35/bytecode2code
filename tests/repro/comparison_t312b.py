def sign(x):
    if x > 0:
        return 1
    elif x < 0:
        return -1
    return 0

def total(*args, **kwargs):
    s = 0
    for a in args:
        s += a
    return s
