import asyncio

def nested(data):
    return [[y for y in row if y] for row in data]

class Base:
    pass

class Child(Base):
    @property
    def value(self):
        return self._v

    @value.setter
    def value(self, v):
        self._v = v

async def main():
    async with asyncio.Lock():
        await asyncio.sleep(0)

def cleanup():
    try:
        return 1
    finally:
        print('cleanup')
