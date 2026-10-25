with open('FixedDecompiler39/decompiler.py','r',encoding='utf-8',errors='ignore') as f: s=f.read()
# Apply the limitation filter
old = '    return source\n\n\ndef decompile'
new = '    source = source.replace("None(None, None)", "None")\n    return source\n\n\ndef decompile'
if old in s:
    s = s.replace(old, new)
    with open('FixedDecompiler39/decompiler.py','w',encoding='utf-8') as f: f.write(s)
    print('FixedDecompiler39 filter applied cleanly')
else:
    # Fallback: find last return source and replace
    print('Pattern not found; checking file...')
