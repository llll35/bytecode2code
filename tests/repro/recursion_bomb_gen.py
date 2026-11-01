# cross_jump_bomb.py
def cross_jump(x):
    if x == 1:
        x = 2
    elif x == 2:
        x = 3
    elif x == 3:
        x = 1
    else:
        return 0
    return cross_jump(x)