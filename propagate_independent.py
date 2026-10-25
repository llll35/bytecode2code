import os
for v in ['310','311','312','313','314','315']:
    path = 'py%sDecompiler/independent_control_flow/control_engine.py' % v
    ver = '3.' + v[-2:]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('# Per-version independent control-flow engine for %s\nVERSION_FLOW = {\n    "%s": "SETUP_FINALLY_POP_BLOCK_RERAISE",\n}\n' % (v, ver))
    print('Wrote', path)
