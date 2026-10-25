import os
with open('FixedDecompiler39/__init__.py','r',encoding='utf-8') as f: s=f.read()
s=s.replace('VERSION = "3.9"','VERSION = "3.9-fixed"')
with open('FixedDecompiler39/__init__.py','w',encoding='utf-8') as f: f.write(s)
print('FixedDecompiler39 已标记 VERSION=3.9-fixed')
print('存在:', os.path.isdir('FixedDecompiler39'))
