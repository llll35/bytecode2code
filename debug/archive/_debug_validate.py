import sys, dis, tempfile, os
sys.path.insert(0, r'd:\py\bytecode2code')

from bytecode2code.pyc_parser import PyCParser
from bytecode2code.decompiler import Decompiler

pyc_file = PyCParser.parse_file(r'd:\py\bytecode2code\tests\samples\prime.pyc')
orig_code = pyc_file.code

# Walk through all consts to find _validate_input
def find_code(co, name):
    for const in co.co_consts:
        if isinstance(const, type(co)):
            if const.co_name == name:
                return const
            result = find_code(const, name)
            if result:
                return result
    return None

orig = find_code(orig_code, '_validate_input')
print('=== Original _validate_input bytecode ===')
dis.dis(orig)
print()

dec = Decompiler()
result = dec.decompile(orig_code)

tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8')
tmp.write(result)
tmp.close()

try:
    src = open(tmp.name, encoding='utf-8').read()
    co2 = compile(src, tmp.name, 'exec')
    decompiled = find_code(co2, '_validate_input')
    print('=== Decompiled _validate_input bytecode ===')
    dis.dis(decompiled)
finally:
    os.unlink(tmp.name)
