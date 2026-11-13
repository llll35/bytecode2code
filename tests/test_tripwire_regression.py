"""Regression tests for tripwire.py using the unchanged comparison rules."""
import ast
import importlib
import itertools
from pathlib import Path
import sys
import textwrap
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tripwire
from tests.equivalence import compare


@unittest.skipUnless((3, 9) <= sys.version_info[:2] <= (3, 15), 'requires an in-tree backend')
class TripwireRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = importlib.import_module('py%d%dDecompiler' % sys.version_info[:2])

    def roundtrip(self, source):
        source = textwrap.dedent(source).lstrip()
        original = compile(source, '<tripwire_regression>', 'exec')
        output = self.backend.decompile(original)
        rebuilt = compile(output, original.co_filename, 'exec')
        self.assertEqual(compare(original, rebuilt), [], output)
        self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(output)), output)
        return original, rebuilt, output

    def test_adversarial_corpus(self):
        for name, (minimum, _) in tripwire.CASES.items():
            with self.subTest(name=name):
                row = tripwire.check_case(name)
                if sys.version_info[:2] < minimum:
                    self.assertEqual(row['status'], 'SKIP')
                else:
                    self.assertEqual(row['status'], 'OK', '\n'.join(row['diffs']) + '\n' + row['output'])
                    self.assertGreater(row['scenarios'], 0)

    @unittest.skipUnless(sys.version_info >= (3, 10), 'match needs Python 3.10+')
    def test_guard_groups_and_negated_operands(self):
        guards = (
            'left(a) and middle(b) or right(a)',
            '(left(a) or middle(b)) and right(a)',
            'left(a) and (middle(b) or right(a))',
            'left(a) or (middle(b) and right(a))',
            'not left(a) and (middle(b) or not right(a))',
            '(left(a) and middle(b)) or (right(a) and left(b))',
        )
        for guard in guards:
            with self.subTest(guard=guard):
                original, rebuilt, output = self.roundtrip('''
                    def f(value, left, middle, right):
                        match value:
                            case [a, b] if %s:
                                return a + b
                            case _:
                                return None
                ''' % guard)
                for results in itertools.product((False, True, 'raise'), repeat=3):
                    options = {'decisions': dict(zip(('left', 'middle', 'right'), results))}
                    self.assertEqual(tripwire.observe(original, 'mixed_and', [2, 3], options),
                                     tripwire.observe(rebuilt, 'mixed_and', [2, 3], options), output)

    @unittest.skipUnless(sys.version_info >= (3, 10), 'match needs Python 3.10+')
    def test_case_body_condition_is_not_part_of_guard(self):
        for header in ('case [a, b]:', 'case [a, b] if gate(a):'):
            with self.subTest(header=header):
                original, rebuilt, output = self.roundtrip('''
                    def f(value, gate, events):
                        match value:
                            %s
                                if gate(b):
                                    events.append('inner')
                                events.append('matched')
                            case _:
                                events.append('other')
                        events.append('after')
                        return events
                ''' % header)
                for a, b in itertools.product((False, True), repeat=2):
                    observations = []
                    for code in (original, rebuilt):
                        namespace, events = {}, []
                        exec(code, namespace)
                        result = namespace['f']([2, 3], lambda n: a if n == 2 else b, events)
                        observations.append((result, list(events)))
                    self.assertEqual(observations[0], observations[1], output)

    @unittest.skipUnless(sys.version_info >= (3, 10), 'match needs Python 3.10+')
    def test_nested_fields_keep_identity_through_rotations(self):
        self.roundtrip('''
            def f(value):
                match value:
                    case [first, [second, *tail], _]:
                        return first + second + len(tail)
                    case _:
                        return None
        ''')
        self.roundtrip('''
            def f(value):
                match value:
                    case Point([head, *tail], y, label=tag):
                        return head + len(tail) + y + len(tag)
                    case _:
                        return None
        ''')
        self.roundtrip('''
            def f(value):
                match value:
                    case {'payload': [head, *tail], 'tag': tag, **rest}:
                        return head + len(tail) + len(tag) + len(rest)
                    case _:
                        return None
        ''')

    @unittest.skipUnless(sys.version_info >= (3, 10), 'match needs Python 3.10+')
    def test_failed_nested_tests_reach_the_next_case(self):
        original, rebuilt, output = self.roundtrip('''
            def f(value):
                match value:
                    case [0, item]:
                        return item
                    case [[1, inner], outer]:
                        return inner + outer
                    case _:
                        return None
        ''')
        for value in (None, [0, 5], [2, 5], [[1, 2], 3], [[2, 2], 3], [[], 3], [[1], 3]):
            self.assertEqual(tripwire.observe(original, 'nested_sequence', value, {}),
                             tripwire.observe(rebuilt, 'nested_sequence', value, {}), output)

    def test_plain_multiline_assignment_stays_assignment(self):
        self.roundtrip('''
            def f(value, gate, events):
                selected = (
                    value
                )
                if gate(selected):
                    events.append('hit')
                events.append('after')
                return events
        ''')

    @unittest.skipUnless(sys.version_info >= (3, 10), 'match needs Python 3.10+')
    def test_guard_factorization_rejects_a_cycle(self):
        reader = importlib.import_module('py%d%dDecompiler.pattern_match' % sys.version_info[:2]).PatternReader
        values = [ast.Name(id=name, ctx=ast.Load()) for name in ('a', 'b', 'c')]
        self.assertIsNone(reader.boolean(values, [(0, 1), (3, 2), (3, 4)]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
