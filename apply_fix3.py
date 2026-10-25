import os
with open('FixedDecompiler39/decompiler.py','r',encoding='utf-8',errors='ignore') as f: fixed=f.read()
folders = ['py39Decompiler','py310Decompiler','py311Decompiler','py312Decompiler','py313Decompiler','py314Decompiler','py315Decompiler']
for folder in folders:
    target = os.path.join(folder,'decompiler.py')
    if os.path.isfile(target):
        with open(target,'w',encoding='utf-8') as f: f.write(fixed)
        print('Applied to', folder)
