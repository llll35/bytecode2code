import dis
src = '''
def f():
    try:
        try:
            try:
                raise OSError('deep error')
            except OSError:
                raise IOError('wrap os error')
        except IOError:
            raise
    except Exception as e:
        print(e)
'''
code = compile(src, "t", "exec")
f = [c for c in code.co_consts if hasattr(c, "co_name") and c.co_name == "f"][0]
for i, ins in enumerate(dis.get_instructions(f)):
    print("%3d %5d %-28s %s" % (i, ins.offset, ins.opname, ins.argrepr))
