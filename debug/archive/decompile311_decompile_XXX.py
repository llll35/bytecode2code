# Source Generated with Decompyle++
# File: decomp311.cpython-39.pyc (Python 3.9)

"""Back-translate CPython 3.11 bytecode into the 3.9 shape.

The project's :class:`bytecode2code.Decompiler` was written against Python
3.9 and keys every decision off ``Instruction.opname``/``argval``.  3.11
renamed half the opcode set and replaced the block stack with a zero cost
exception table, but the *abstract* operations the decompiler emulates are
unchanged.

This module rewrites a 3.11 instruction stream into the equivalent 3.9
stream -- keeping the original byte offsets, so every jump target stays valid
-- and hands the result to the stock decompiler.  The rewriting is purely
syntactic; the decompiler keeps doing all the work.

3.12 is deliberately not claimed here: it inlines comprehensions into the
enclosing code object instead of calling a nested one, which this translation
does not yet reconstruct.
"""
import dis
import sys
from bytecode2code import Instruction
from decomp_compat import Decompiler310
NB_TO_OPCODE = {
    'NB_ADD': 'BINARY_ADD',
    'NB_SUBTRACT': 'BINARY_SUBTRACT',
    'NB_MULTIPLY': 'BINARY_MULTIPLY',
    'NB_FLOOR_DIVIDE': 'BINARY_FLOOR_DIVIDE',
    'NB_TRUE_DIVIDE': 'BINARY_TRUE_DIVIDE',
    'NB_REMAINDER': 'BINARY_MODULO',
    'NB_POWER': 'BINARY_POWER',
    'NB_LSHIFT': 'BINARY_LSHIFT',
    'NB_RSHIFT': 'BINARY_RSHIFT',
    'NB_AND': 'BINARY_AND',
    'NB_XOR': 'BINARY_XOR',
    'NB_OR': 'BINARY_OR',
    'NB_MATRIX_MULTIPLY': 'BINARY_MATRIX_MULTIPLY',
    'NB_INPLACE_ADD': 'INPLACE_ADD',
    'NB_INPLACE_SUBTRACT': 'INPLACE_SUBTRACT',
    'NB_INPLACE_MULTIPLY': 'INPLACE_MULTIPLY',
    'NB_INPLACE_FLOOR_DIVIDE': 'INPLACE_FLOOR_DIVIDE',
    'NB_INPLACE_TRUE_DIVIDE': 'INPLACE_TRUE_DIVIDE',
    'NB_INPLACE_REMAINDER': 'INPLACE_MODULO',
    'NB_INPLACE_POWER': 'INPLACE_POWER',
    'NB_INPLACE_LSHIFT': 'INPLACE_LSHIFT',
    'NB_INPLACE_RSHIFT': 'INPLACE_RSHIFT',
    'NB_INPLACE_AND': 'INPLACE_AND',
    'NB_INPLACE_XOR': 'INPLACE_XOR',
    'NB_INPLACE_OR': 'INPLACE_OR',
    'NB_INPLACE_MATRIX_MULTIPLY': 'INPLACE_MATRIX_MULTIPLY' }

def _nb_opcode(arg):
