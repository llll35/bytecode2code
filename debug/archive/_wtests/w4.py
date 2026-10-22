async def f(a, b):
    async with a as x, b as y:
        return x + y
