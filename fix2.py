with open('FixedDecompiler39/decompiler.py','r',encoding='utf-8',errors='ignore') as f: s=f.read()
old = '    return source\n\n\ndef decompile'
new = '    source = source.replace("None(None, None)", "None")\n    return source\n\n\ndef decompile'
s = s.replace(old, new)
with open('FixedDecompiler39/decompiler.py','w',encoding='utf-8') as f: f.write(s)
print('patched ok')
