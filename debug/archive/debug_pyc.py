from bytecode2code.pyc_parser import PyCParser
from bytecode2code.disassembler import Disassembler

pyc_file = PyCParser.parse_file('bytecode2code/prime.pyc')
print(f'magic: {pyc_file.magic!r}')
print(f'flags: {pyc_file.flags:#010x}')
print(f'code name: {pyc_file.code.co_name}')

d = Disassembler()
for instr in d.disassemble(pyc_file.code):
    print(f'{instr.offset:4d} {instr.opname:25s} arg={instr.arg!r:8s} argval={instr.argval!r} line={instr.line_no}')
