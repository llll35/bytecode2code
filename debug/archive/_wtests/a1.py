async def f(a):
    async with a as x:
        return x + 1
