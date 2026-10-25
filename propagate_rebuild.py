import os
for v in ['39','310','311','312','313','314','315']:
    folder = 'py%sDecompiler/independent_control_flow' % v
    ver = '3.' + v[-2:] if v != '315' else '3.15'
    path = os.path.join(folder, 'rebuild_engine.py')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('# Per-version independent rebuild engine for %s\nVERSION_FLOW = {\n    "%s": "SETUP_FINALLY_RERAISE_INDEPENDENT",\n}\n' % (v, ver))
    print('Wrote', path)
