async def f(a):
    async with a as x:
        try:
            pass
        except ValueError:
            pass
