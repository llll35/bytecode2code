"""Focused regressions for nightmare.py, without changing the legacy gate.

Run this script with each interpreter under embed_python/python-X.Y/.
All code-object comparisons use the existing, unmodified comparison rules.
"""
import ast
import importlib
import os
import sys
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.equivalence import compare


@unittest.skipUnless((3, 9) <= sys.version_info[:2] <= (3, 15),
                     'requires a supported CPython backend')
class NightmareRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = importlib.import_module('py%d%dDecompiler' % sys.version_info[:2])

    def roundtrip(self, source, *, structure=True):
        source = textwrap.dedent(source).lstrip()
        original = compile(source, '<nightmare_regression>', 'exec')
        output = self.backend.decompile(original)
        rebuilt = compile(output, original.co_filename, 'exec')
        self.assertEqual(compare(original, rebuilt), [], output)
        if structure:
            self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(output)), output)
        return original, rebuilt, output

    def test_conditional_break_keeps_false_and_exception_edges(self):
        original, rebuilt, output = self.roundtrip('''
            def f(x):
                while True:
                    try:
                        if x:
                            break
                    except ValueError:
                        pass
                    finally:
                        print(1)
                return x
        ''')
        for decisions in ((True,), (False, True), (ValueError, False, True), (TypeError,)):
            observations = []
            for code in (original, rebuilt):
                events, steps = [], iter(decisions)

                class Condition:
                    def __bool__(self):
                        step = next(steps)
                        events.append(('test', step))
                        if isinstance(step, type):
                            raise step('injected')
                        return step

                value = Condition()
                namespace = {'print': lambda item: events.append(('finally', item))}
                exec(code, namespace)
                try:
                    result = ('return', namespace['f'](value) is value)
                except BaseException as error:
                    result = ('raise', type(error).__name__, str(error))
                observations.append((result, events))
            self.assertEqual(observations[0], observations[1], output)

    def test_while_break_return_is_evaluated_after_nested_finally(self):
        original, rebuilt, output = self.roundtrip('''
            def f(data):
                i = 0
                while True:
                    try:
                        if i >= len(data):
                            break
                        try:
                            print(data[i])
                        except IndexError:
                            break
                        finally:
                            i += 1
                    finally:
                        print('tick')
                return i
        ''')

        class FailingData:
            def __init__(self, error):
                self.error = error

            def __len__(self):
                return 3

            def __getitem__(self, index):
                raise self.error('injected')

        for data in ([], [10, 20], FailingData(IndexError), FailingData(ValueError)):
            observations = []
            for code in (original, rebuilt):
                events = []
                namespace = {'print': events.append}
                exec(code, namespace)
                try:
                    result = ('return', namespace['f'](data))
                except BaseException as error:
                    result = ('raise', type(error).__name__, str(error))
                observations.append((result, events))
            self.assertEqual(observations[0], observations[1], output)
            if isinstance(data, FailingData) and data.error is IndexError:
                self.assertEqual(observations[1], (('return', 1), ['tick']))

    def test_source_return_inside_loop_is_not_a_threaded_break(self):
        self.roundtrip('''
            def f(x):
                while True:
                    try:
                        if x:
                            return x
                    except ValueError:
                        pass
                    finally:
                        print(1)
        ''')
        self.roundtrip('''
            def f(x):
                while True:
                    try:
                        work()
                    finally:
                        if x:
                            return x
        ''')

    def test_nested_finally_latch_does_not_suppress_exceptions(self):
        original, rebuilt, output = self.roundtrip('''
            def f(data, out):
                for value in data:
                    try:
                        out.append(int(value))
                    except ValueError as error:
                        out.append(str(error))
                        continue
                    finally:
                        try:
                            out.append('deep')
                        finally:
                            out.append('deepest')
                return out
        ''')

        class Recorder(list):
            def append(self, value):
                super().append(value)
                if value == 'deep':
                    raise RuntimeError('cleanup failed')

        for data in (['1'], ['bad'], [None]):
            observations = []
            for code in (original, rebuilt):
                namespace, out = {}, Recorder()
                exec(code, namespace)
                try:
                    result = ('return', namespace['f'](data, out))
                except BaseException as error:
                    result = ('raise', type(error).__name__, str(error))
                observations.append((result, list(out)))
            self.assertEqual(observations[0], observations[1], output)
            self.assertEqual(observations[1][0], ('raise', 'RuntimeError', 'cleanup failed'))

    @unittest.skipUnless(sys.version_info[:2] == (3, 9), '3.9 retains the unreachable else instructions')
    def test_retained_while_true_else(self):
        self.roundtrip('''
            def f(data):
                while True:
                    try:
                        if data:
                            break
                    finally:
                        print('cleanup')
                else:
                    print('unreachable but retained')
                return data
        ''')

    @unittest.skipUnless(sys.version_info >= (3, 10), 'match needs Python 3.10+')
    def test_match_literals_subject_once_and_continuation(self):
        original, rebuilt, output = self.roundtrip('''
            def f(subject, events):
                match subject():
                    case 0:
                        events.append('zero')
                    case 1 | 2:
                        events.append('small')
                    case _:
                        events.append('other')
                events.append('after')
                return events
        ''')
        for value in (0, 1, 2, 3, '1', None):
            observations = []
            for code in (original, rebuilt):
                namespace, events = {}, []
                exec(code, namespace)

                def subject():
                    events.append('subject')
                    return value

                result = namespace['f'](subject, events)
                observations.append((result, list(events)))
                self.assertEqual(events.count('subject'), 1)
            self.assertEqual(observations[0], observations[1], output)
        self.roundtrip('''
            match 3:
                case 3:
                    selected = 'hit'
                case _:
                    selected = 'miss'
        ''')

    @unittest.skipUnless(sys.version_info >= (3, 10), 'match needs Python 3.10+')
    def test_match_mapping_rest_class_alias_sequence_guard(self):
        original, rebuilt, output = self.roundtrip('''
            def f(value):
                match value:
                    case {'left': a, 'right': b} if a > b:
                        return a - b
                    case {'left': a, **rest}:
                        return a + len(rest)
                    case str() | bytes() as text:
                        return len(text)
                    case [first, *tail] if tail:
                        return first
                    case _:
                        return None
        ''')
        for value in (None, 10, {}, {'left': 8, 'right': 2}, {'left': 1, 'right': 5},
                      {'left': 3, 'extra': 4}, 'hello', b'ab', [], [1], [2, 3], (4, 5),
                      {'left': object(), 'right': 2}):
            observations = []
            for code in (original, rebuilt):
                namespace = {}
                exec(code, namespace)
                try:
                    result = ('return', namespace['f'](value))
                except BaseException as error:
                    result = ('raise', type(error).__name__, str(error))
                observations.append(result)
            self.assertEqual(observations[0], observations[1], output)

    @unittest.skipUnless(sys.version_info >= (3, 10), 'match needs Python 3.10+')
    def test_match_class_fields_capture_and_loop_exits(self):
        self.roundtrip('''
            def f(value):
                match value:
                    case Point(x, y, label=tag) if x > y:
                        return tag
                    case other:
                        return other
        ''')
        original, rebuilt, output = self.roundtrip('''
            def f(data):
                out = []
                for value in data:
                    match value:
                        case 0:
                            break
                        case 1:
                            continue
                        case _:
                            out.append(value)
                return out
        ''')
        for data in ([], [2, 1, 3], [1, 0, 4], [3, 0, 2]):
            results = []
            for code in (original, rebuilt):
                namespace = {}
                exec(code, namespace)
                results.append(namespace['f'](data))
            self.assertEqual(results[0], results[1], output)

    @unittest.skipUnless(sys.version_info >= (3, 10), 'match needs Python 3.10+')
    def test_match_no_wildcard_and_singletons(self):
        self.roundtrip('''
            def f(value):
                match value:
                    case 0:
                        return 'zero'
                    case 1:
                        return 'one'
        ''')
        self.roundtrip('''
            def f(value):
                match value:
                    case None:
                        return 'none'
                    case True:
                        return 'true'
                    case False:
                        return 'false'
                    case _:
                        return 'other'
        ''')

    @unittest.skipUnless(sys.version_info >= (3, 10), 'match needs Python 3.10+')
    def test_match_guard_short_circuit_and_indentation(self):
        for operator in ('and', 'or'):
            with self.subTest(operator=operator):
                original, rebuilt, output = self.roundtrip('''
                    def f(value, left, right):
                        match value:
                            case [a, b] if left(a) %s right(b):
                                return a + b
                            case _:
                                return None
                ''' % operator)
                for left_result, right_result in ((False, False), (False, True), (True, False), (True, True)):
                    observations = []
                    for code in (original, rebuilt):
                        namespace, events = {}, []
                        exec(code, namespace)

                        def left(value):
                            events.append(('left', value))
                            return left_result

                        def right(value):
                            events.append(('right', value))
                            return right_result

                        observations.append((namespace['f']([2, 3], left, right), events))
                    self.assertEqual(observations[0], observations[1], output)
        self.roundtrip("def f(x):\n  match x:\n    case 0:\n      return 'zero'\n    case _:\n      return 'other'\n")

    def test_multiline_comparison_is_not_match(self):
        self.roundtrip('''
            def f(value, events):
                if (value ==
                        0):
                    events.append('zero')
                else:
                    events.append('other')
                events.append('after')
                return events
        ''')

    def test_irrecoverable_source_shapes_are_not_guessed(self):
        if sys.version_info < (3, 11):
            pairs = ((
                "def f(data):\n    for value in data:\n        print(value)\n    else:\n        print('done')\n",
                "def f(data):\n    for value in data:\n        print(value)\n\n    print('done')\n",
            ), (
                "def f():\n    return\n",
                "def f():\n    return None\n",
            ))
        else:
            pairs = ()
        if sys.version_info >= (3, 10):
            import nightmare
            dead_else = nightmare._source(next(source for name, _, source in nightmare.SNIPPETS
                                               if name == 'while_true_try_finally'))
            pairs += ((dead_else, dead_else.replace("print('never')", "print('other')")),)
        for left, right in pairs:
            with self.subTest(left=left):
                originals = [compile(source, '<same_metadata>', 'exec') for source in (left, right)]
                self.assertNotEqual(ast.dump(ast.parse(left)), ast.dump(ast.parse(right)))
                self.assertEqual(compare(*originals), [])
                nested = [next(c for c in code.co_consts if hasattr(c, 'co_code')) for code in originals]
                self.assertEqual(nested[0].co_code, nested[1].co_code)
                self.assertEqual(nested[0].co_consts, nested[1].co_consts)
                table = 'co_lnotab' if sys.version_info < (3, 11) else 'co_linetable'
                self.assertEqual(getattr(nested[0], table), getattr(nested[1], table))
                self.assertEqual(self.backend.decompile(originals[0]), self.backend.decompile(originals[1]))

    def test_distinct_finally_copies(self):
        for clauses in (('print(1)', 'print(2)', 'print(3)'),
                        ('first(x)', 'second(x)', 'third(x)')):
            with self.subTest(clauses=clauses):
                self.roundtrip('''
                    def f(x):
                        try:
                            try:
                                try:
                                    return x
                                finally:
                                    %s
                            finally:
                                %s
                        finally:
                            %s
                ''' % clauses)

    def test_nested_and_multi_manager_with(self):
        for depth in (2, 6):
            lines = ['def f(x, cm):']
            for level in range(depth):
                lines.append('    ' * (level + 1) + "with cm(%d) as a%d:" % (level, level))
            lines += ['    ' * (depth + 1) + 'x += 1', '    return x']
            with self.subTest(depth=depth):
                self.roundtrip('\n'.join(lines) + '\n')
        self.roundtrip('''
            def f(x, cm):
                with cm(1) as a, cm(2) as b:
                    x += 1
                return x
        ''')

    @unittest.skipUnless(sys.version_info >= (3, 11), 'else indentation needs PEP 657 positions')
    def test_for_else_before_finally(self):
        self.roundtrip('''
            def f(data):
                for value in data:
                    print(value)
                else:
                    print('done')
                try:
                    return 1
                finally:
                    print('cleanup')
        ''')

    @unittest.skipUnless(sys.version_info >= (3, 14), '3.14+ source-boundary regression')
    def test_adjacent_for_is_not_else(self):
        self.roundtrip('''
            def f(data):
                for value in data:
                    print(value)
                for other in data:
                    print(other)
                return 1
        ''')
        self.roundtrip('''
            def f(data):
                for value in data:
                    print(value)
                else:
                    for other in data:
                        print(other)
                return 1
        ''')

    def test_generator_exit_preserves_return_and_cleanup(self):
        for returned in ('return', 'return None'):
            with self.subTest(returned=returned):
                original, rebuilt, output = self.roundtrip('''
                    def f(data):
                        for item in data:
                            try:
                                yield item
                            except GeneratorExit:
                                %s
                            finally:
                                print(item)
                ''' % returned, structure=sys.version_info >= (3, 11))
                # 3.9/3.10 have no column metadata to distinguish the two
                # return spellings. Their bytecode and exit behavior still
                # have to match; nightmare.py's stricter AST check is unchanged.
                for mode in ('normal', 'close', 'throw_exit', 'throw_error'):
                    observations = []
                    for code in (original, rebuilt):
                        events = []
                        namespace = {'print': events.append}
                        exec(code, namespace)
                        gen = namespace['f']([1, 2, 3])
                        values, outcome = [], None
                        try:
                            if mode == 'normal':
                                values = list(gen)
                            else:
                                values.append(next(gen))
                                if mode == 'close':
                                    outcome = ('return', gen.close())
                                elif mode == 'throw_exit':
                                    gen.throw(GeneratorExit())
                                else:
                                    gen.throw(ValueError('injected'))
                        except BaseException as error:
                            outcome = (type(error).__name__, str(error))
                        finally:
                            gen.close()
                        observations.append((values, events, outcome))
                    self.assertEqual(observations[0], observations[1], output)
                    self.assertEqual(observations[1][1], [1, 2, 3] if mode == 'normal' else [1])

    def test_none_return_in_loop_handler_is_not_epilogue(self):
        original, rebuilt, output = self.roundtrip('''
            def f(data, events):
                for item in data:
                    try:
                        work(item)
                    except ValueError:
                        return None
                    finally:
                        events.append(item)
                events.append('done')
        ''')

        def work(value):
            if value < 0:
                raise ValueError(value)

        for data in ([], [1, 2], [-1, 2], [1, -1, 3]):
            observations = []
            for code in (original, rebuilt):
                namespace, events = {'work': work}, []
                exec(code, namespace)
                observations.append((namespace['f'](data, events), events))
            self.assertEqual(observations[0], observations[1], output)

    @unittest.skipUnless(sys.version_info >= (3, 11), 'except* needs Python 3.11+')
    def test_except_star_wrappers_and_real_nesting(self):
        for source in ('''
            def f(fn):
                try:
                    fn()
                except* ValueError as error:
                    print('value', error)
                else:
                    print('else')
        ''', '''
            def f(fn):
                try:
                    fn()
                except* ValueError as error:
                    print('value', error)
                finally:
                    print('finally')
        ''', '''
            def f(fn):
                try:
                    try:
                        fn()
                    except* ValueError as error:
                        print('value', error)
                finally:
                    print('finally')
        ''', '''
            def f(fn, cm):
                with cm('a') as handle:
                    try:
                        fn(handle)
                    except* ValueError as error:
                        print(error)
        ''', '''
            def f(fn):
                try:
                    try:
                        try:
                            fn()
                        except* KeyError:
                            print('key')
                    except* ValueError:
                        print('value')
                except* TypeError:
                    print('type')
                finally:
                    print('done')
        '''):
            with self.subTest(source=source):
                self.roundtrip(source)

    @unittest.skipUnless(sys.version_info >= (3, 11), 'except* needs Python 3.11+')
    def test_except_star_else_finally_and_continuation(self):
        original, rebuilt, output = self.roundtrip('''
            def f(fn, events):
                try:
                    fn()
                except* ValueError as error:
                    events.append(('value', len(error.exceptions)))
                except* TypeError:
                    events.append('type')
                else:
                    events.append('else')
                finally:
                    events.append('finally')
                events.append('after')
        ''')

        def describe(error):
            if isinstance(error, BaseExceptionGroup):
                return type(error).__name__, tuple(describe(e) for e in error.exceptions)
            return type(error).__name__, str(error)

        for error in (None, ValueError('plain'), TypeError('plain'),
                      ExceptionGroup('mixed', [ValueError('a'), TypeError('b'), KeyError('c')])):
            observations = []
            for code in (original, rebuilt):
                namespace, events = {}, []
                exec(code, namespace)

                def fn():
                    if error is not None:
                        raise error

                try:
                    result = ('return', namespace['f'](fn, events))
                except BaseException as raised:
                    result = ('raise', describe(raised))
                observations.append((result, events))
            self.assertEqual(observations[0], observations[1], output)


if __name__ == '__main__':
    unittest.main(verbosity=2)
