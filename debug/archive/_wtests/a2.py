async def f(a):
    async with a as x:
        v = x + 1
    return v
