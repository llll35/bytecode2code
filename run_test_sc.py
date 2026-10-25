import sys, py_compile, tempfile, os, importlib
sys.path.insert(0,'.')
with open('test_sc.py','r',encoding='utf-8') as f: src=f.read()
with tempfile.NamedTemporaryFile(suffix='.py',delete=False,mode='w',encoding='utf-8') as t:
    t.write(src); p=t.name
pyc=p.replace('.py','.pyc')
py_compile.compile(p,cfile=pyc,doraise=True)

parser=importlib.import_module('FixedDecompiler39.pyc_parser')
parsed=parser.PyCParser.parse_file(pyc)
dec=importlib.import_module('FixedDecompiler39').decompile(parsed.code)
print('=== FIXED OUTPUT (first 20 lines) ===')
for line in dec.splitlines()[:20]: print(line)
print('... total lines:', len(dec.splitlines()))
bad='None(None, None)' in dec
print('Contains invalid None(None, None):', bad)
print('Contains del e:', 'del e' in dec)
try:
    import ast
    ast.parse(dec)
    print('AST PARSE: OK')
except Exception as e:
    print('AST PARSE FAIL:', e)
