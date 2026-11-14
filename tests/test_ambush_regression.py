"""Mixed ordinary Boolean control flow: strict structure and behavior checks."""
import ast
import importlib
import itertools
from pathlib import Path
import sys
import textwrap
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ambush
from tests.equivalence import compare


@unittest.skipUnless((3, 9) <= sys.version_info[:2] <= (3, 15), 'requires a supported backend')
class AmbushRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = importlib.import_module('py%d%dDecompiler' % sys.version_info[:2])

    def roundtrip(self, source):
        source = textwrap.dedent(source).lstrip()
        original = compile(source, '<ambush_regression>', 'exec')
        output = self.backend.decompile(original)
        rebuilt = compile(output, original.co_filename, 'exec')
        self.assertEqual(compare(original, rebuilt), [], output)
        self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(output)), output)
        return original, rebuilt, output

    def test_adversarial_corpus(self):
        for name in ambush.CASES:
            with self.subTest(name=name):
                row = ambush.check_case(name)
                self.assertEqual(row['status'], 'OK', '\n'.join(row['diffs']) + '\n' + row['output'])
                self.assertEqual(row['scenarios'], 62 if 'finally' in name else 31)

    def test_body_condition_remains_a_nested_if(self):
        original, rebuilt, output = self.roundtrip('''
            def f(a, b, c, events):
                if a and (b or c):
                    if b:
                        events.append('inner')
                    events.append('hit')
                else:
                    events.append('miss')
                events.append('after')
                return events
        ''')
        for stream, _ in ambush.scenarios('if_and_or'):
            self.assertEqual(ambush.observe(original, stream), ambush.observe(rebuilt, stream), output)

    def test_existing_flat_conditions_keep_their_shape(self):
        for condition in ('a and b and c', 'a or b or c', 'not (a or b or c)', 'not (a and b and c)'):
            with self.subTest(condition=condition):
                self.roundtrip(ambush._branch(condition))

    def test_value_expression_keeps_the_returned_operand(self):
        original, rebuilt, output = self.roundtrip('''
            def f(a, b, c):
                return a and (b or c)
        ''')
        for values in itertools.product((False, True, 'raise'), repeat=3):
            observations = []
            for code in (original, rebuilt):
                namespace, events = {}, []
                exec(code, namespace)
                switches = [ambush.Switch(name, (value,), events) for name, value in zip(('a', 'b', 'c'), values)]
                try:
                    result = namespace['f'](*switches)
                    outcome = 'return', next(i for i, switch in enumerate(switches) if result is switch)
                except BaseException as error:
                    outcome = 'raise', ambush._exception(error)
                observations.append((outcome, events))
            self.assertEqual(observations[0], observations[1], output)

    def test_named_expression_operand_is_not_a_separate_assignment(self):
        for condition in ('(picked := a) and (b or c)', 'a and ((picked := b) or c)'):
            with self.subTest(condition=condition):
                original, rebuilt, output = self.roundtrip(ambush._branch(condition))
                for stream, _ in ambush.scenarios('if_and_or'):
                    self.assertEqual(ambush.observe(original, stream), ambush.observe(rebuilt, stream), output)

    def test_call_operands_execute_once_and_in_order(self):
        original, rebuilt, output = self.roundtrip('''
            def f(a, b, c, events):
                if a() and (b() or c()):
                    events.append('hit')
                else:
                    events.append('miss')
                events.append('after')
                return events
        ''')
        for stream, _ in ambush.scenarios('if_and_or'):
            observations = []
            for code in (original, rebuilt):
                namespace, events = {}, []
                exec(code, namespace)
                switches = [ambush.Switch(name, values, events) for name, values in zip(('a', 'b', 'c'), stream)]

                def predicate(switch):
                    def call():
                        events.append(('call', switch.name))
                        return switch
                    return call

                try:
                    result = namespace['f'](*(predicate(switch) for switch in switches), events)
                    outcome = 'return', list(result)
                except BaseException as error:
                    outcome = 'raise', ambush._exception(error)
                observations.append((outcome, list(events)))
            self.assertEqual(observations[0], observations[1], output)

    def test_graph_with_a_cycle_is_not_guessed(self):
        graph = importlib.import_module('py%d%dDecompiler.condition_graph' % sys.version_info[:2])
        operands = [ast.Name(id=name, ctx=ast.Load()) for name in ('a', 'b', 'c')]
        self.assertIsNone(graph._factor(operands, [(0, 1), (3, 2), (3, 4)]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
