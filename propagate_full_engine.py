import os, shutil
for v in ['310','311','312','313','314','315']:
    src = 'py39Decompiler/independent_control_flow/full_engine.py'
    dst = 'py%sDecompiler/independent_control_flow/full_engine.py' % v
    shutil.copy(src, dst)
    # Adjust version reference inside file if needed
    with open(dst, 'r', encoding='utf-8') as f: s = f.read()
    s = s.replace('py39', 'py%s' % v)
    with open(dst, 'w', encoding='utf-8') as f: f.write(s)
    print('Copied full_engine to', dst)
