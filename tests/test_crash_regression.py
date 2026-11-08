"""Regression for the stack/control-flow crash_test.py reported by the user.

Run under each supported interpreter: python tests/test_crash_regression.py.
"""

import ast
import contextlib
import importlib
import io
import os
import sys
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.control_flow_cases import INPUTS
from tests.equivalence import compare
from tests.test_modern_control_flow import execute as execute_probe
from tests.test_roundtrip import Result


FIXTURE = os.path.join(os.path.dirname(__file__), 'repro', 'crash_stack.py')


@unittest.skipUnless((3, 9) <= sys.version_info[:2] <= (3, 15),
                     'requires a supported CPython backend')
class CrashRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = importlib.import_module('py%d%dDecompiler' % sys.version_info[:2])
        with open(FIXTURE, encoding='utf-8') as handle:
            cls.source = handle.read()
        cls.original = compile(cls.source, '<crash_stack>', 'exec')
        cls.output = cls.backend.decompile(cls.original)
        cls.rebuilt = compile(cls.output, cls.original.co_filename, 'exec')

    def test_reported_source_structure(self):
        self.assertEqual(ast.dump(ast.parse(self.source)),
                         ast.dump(ast.parse(self.output)), self.output)

    def test_reported_roundtrip(self):
        self.assertEqual(compare(self.original, self.rebuilt), [], self.output)

    def test_reported_behaviour(self):
        namespaces = []
        for code in (self.original, self.rebuilt):
            namespace = {'__name__': 'crash_stack'}
            exec(code, namespace)
            namespaces.append(namespace)

        def invoke(namespace, name, args):
            try:
                return 'return', namespace[name](*args)
            except Exception as error:
                return 'raise', type(error).__name__, str(error)

        cases = {
            'tricky_func': [(a, b) for a in (-2, 0, 1, 5, 101)
                            for b in (-1, 0, 6, 200, None, 'bad')],
            'nested_chaos': [(n,) for n in range(-2, 31)] + [(1.5,), (None,)],
            'walrus_and_shortcut': [(list(range(n)),) for n in range(9)]
                                  + [([0] * n,) for n in range(9)],
            'gen_and_nested': [()],
            'unpack_mess': [()],
        }
        for name, inputs in cases.items():
            for args in inputs:
                with self.subTest(function=name, args=args):
                    self.assertEqual(invoke(namespaces[0], name, args),
                                     invoke(namespaces[1], name, args), self.output)

    def test_module_entry_point(self):
        outputs = []
        for code in (self.original, self.rebuilt):
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                exec(code, {'__name__': '__main__'})
            outputs.append(stream.getvalue())
        self.assertEqual(outputs[0], outputs[1], self.output)
        self.assertEqual(len(outputs[1].splitlines()), 5)

    def check_probe(self, source, *, structure=False):
        source = textwrap.dedent(source).lstrip()
        original = compile(source, '<crash_probe>', 'exec')
        output = self.backend.decompile(original)
        rebuilt = compile(output, original.co_filename, 'exec')
        if structure:
            self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(output)), output)
        self.assertEqual(compare(original, rebuilt), [], output)
        for data in INPUTS + (('return', 2), (0, 'return', 2)):
            with self.subTest(data=data):
                self.assertEqual(execute_probe(original, data), execute_probe(rebuilt, data), output)

    def test_loop_handler_boundaries(self):
        for handler in ('ValueError', 'ValueError as error'):
            for returned in ('out', 'out + len(events)', 'work(out)'):
                with self.subTest(handler=handler, returned=returned):
                    self.check_probe('''
                        def f(data, events):
                            out = 0
                            for value in data:
                                try:
                                    if value == 'skip':
                                        continue
                                    if value == 'stop':
                                        break
                                    tmp = work(value)
                                except %s:
                                    events.append('except')
                                else:
                                    out += tmp
                            return %s
                    ''' % (handler, returned))

    def test_independent_loop_return(self):
        for returned in ('out', 'None'):
            with self.subTest(returned=returned):
                self.check_probe('''
                    def f(data, events):
                        out = 0
                        for value in data:
                            if value == 'return':
                                return %s
                            out += work(value)
                        return out
                ''' % returned, structure=True)

    def test_finally_return_evaluated_once(self):
        for returned in ('work(len(events))', 'len(events)', 'None'):
            with self.subTest(returned=returned):
                self.check_probe('''
                    def f(data, events):
                        try:
                            value = work(data[0])
                        except ValueError as error:
                            events.append('except')
                        finally:
                            events.append('finally')
                            return %s
                ''' % returned)

    def test_short_circuit_walrus(self):
        for operator in ('and', 'or'):
            with self.subTest(operator=operator):
                self.check_probe('''
                    def f(data, events):
                        if (k := len(data)) > 4 %s (value := work(data[-1])) != 0:
                            return k
                        return -1
                ''' % operator, structure=True)


def run():
    """Report these checks separately without changing the legacy gate counts."""
    if not (3, 9) <= sys.version_info[:2] <= (3, 15):
        return []
    rows = []

    class Results(unittest.TestResult):
        def startTest(self, test):
            self._failure_start = len(self.failures)
            self._error_start = len(self.errors)
            super().startTest(test)

        def stopTest(self, test):
            errors = self.failures[self._failure_start:] + self.errors[self._error_start:]
            diffs = ['%s: %s' % (failed, detail[-2000:]) for failed, detail in errors]
            rows.append(Result('crash_' + test._testMethodName.removeprefix('test_'), not diffs, diffs))
            super().stopTest(test)

    result = Results()
    unittest.defaultTestLoader.loadTestsFromTestCase(CrashRegressionTests).run(result)
    if not rows:
        diffs = [detail[-2000:] for _, detail in result.errors] or ['suite did not run']
        rows.append(Result('crash_suite', False, diffs))
    return rows


if __name__ == '__main__':
    unittest.main(verbosity=2)
