import asyncio

class Animal:
    def __init__(self, name):
        self.name = name
    def speak(self):
        raise NotImplementedError

async def fetch(x):
    await asyncio.sleep(0.1)
    return x * 2

def risky():
    try:
        with open('nofile.txt') as f:
            return f.read()
    except FileNotFoundError as e:
        return str(e)
    finally:
        print('done')

def gen(n):
    for i in range(n):
        yield i * i

@staticmethod
def deco(fn):
    return fn
