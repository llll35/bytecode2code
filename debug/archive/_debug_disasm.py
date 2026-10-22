import dis
import bytecode2code.pyc_parser as pp
p = pp.PyCParser.parse_file('bytecode2code/prime.pyc')
codes = pp.collect_code_objects(p.code)
for depth, code in codes:
    print(f'=== {code.co_name} (depth={depth}) ===')
    dis.dis(code)
    print()
