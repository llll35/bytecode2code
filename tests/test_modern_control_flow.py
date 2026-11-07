"""Structural, exception-region and observable-behaviour control-flow checks.

Run with each target interpreter: python tests/test_modern_control_flow.py.
"""

import ast
import asyncio
import importlib
import inspect
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.control_flow_cases import INPUTS, SOURCES


def execute(code, data, close_generator=False):
    events = []

    class Context:
        def __init__(self, name, suppress=False):
            self.name = name
            self.suppress = suppress

        def __enter__(self):
            events.append(('enter', self.name))
            if self.name == 'enter-error':
                raise RuntimeError(self.name)
            return 7

        def __exit__(self, kind, value, tb):
            events.append(('exit', self.name, None if kind is None else kind.__name__))
            if self.name == 'exit-error':
                raise RuntimeError(self.name)
            return self.suppress and kind is ValueError

        async def __aenter__(self):
            return self.__enter__()

        async def __aexit__(self, kind, value, tb):
            return self.__exit__(kind, value, tb)

    def work(value):
        events.append(('work', value))
        if value in ('bad', 'skip', 'stop'):
            raise ValueError(value)
        if value == 'type':
            raise TypeError(value)
        return value

    async def awork(value):
        await asyncio.sleep(0)
        return work(value)

    async def aiter_values(values):
        for value in values:
            await asyncio.sleep(0)
            yield value

    namespace = dict(cm=Context, acm=Context, work=work, awork=awork,
                     errors=types.SimpleNamespace(ValueError=ValueError, TypeError=TypeError),
                     aiter_values=aiter_values)
    exec(code, namespace)
    # A wrongly recovered back edge must fail the test, not hang the runner.
    budget = [20000]

    def trace(frame, event, arg):
        if event == 'line' and frame.f_code.co_filename == code.co_filename:
            budget[0] -= 1
            if budget[0] <= 0:
                raise RuntimeError('control-flow step limit')
        return trace

    previous = sys.gettrace()
    sys.settrace(trace)
    try:
        result = namespace['f'](list(data), events)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        elif inspect.isasyncgen(result):
            async def consume(generator):
                if close_generator == 'throw':
                    values = [await generator.__anext__()]
                    try:
                        values.append(await generator.athrow(ValueError('injected')))
                    except StopAsyncIteration:
                        pass
                    values.extend([value async for value in generator])
                    return values
                if close_generator:
                    value = await generator.__anext__()
                    await generator.aclose()
                    return value
                return [value async for value in generator]
            result = asyncio.run(consume(result))
        elif inspect.isgenerator(result):
            if close_generator == 'throw':
                generator = result
                result = [next(generator)]
                try:
                    result.append(generator.throw(ValueError('injected')))
                except StopIteration:
                    pass
                result.extend(list(generator))
            elif close_generator:
                generator = result
                result = next(generator, None)
                generator.close()
            else:
                result = list(result)
        return ('return', result), events
    except BaseException as error:
        def exception_shape(value, seen=None):
            if value is None:
                return None
            seen = set() if seen is None else seen
            if id(value) in seen:
                return ('cycle', type(value).__name__)
            seen.add(id(value))
            members = tuple(exception_shape(member, set(seen))
                            for member in getattr(value, 'exceptions', ()))
            cause = exception_shape(value.__cause__, set(seen))
            context = None if value.__suppress_context__ else exception_shape(value.__context__, set(seen))
            return type(value).__name__, str(value), members, cause, context

        return ('raise', exception_shape(error)), events
    finally:
        sys.settrace(previous)


@unittest.skipUnless((3, 11) <= sys.version_info[:2] <= (3, 13),
                     'requires a target control-flow backend')
class ModernControlFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = 'py%d%dDecompiler' % sys.version_info[:2]
        cls.backend = importlib.import_module(package)
        cls.rewriter = importlib.import_module(package + '.decomp311').Rewriter
        cls.analyzer = importlib.import_module(package + '.cfg_flow').ExceptionAnalyzer
        cls.compiled = {}
        for name, source in SOURCES.items():
            original = compile(source, '<flow:%s>' % name, 'exec')
            try:
                output = cls.backend.decompile(original)
                rebuilt = compile(output, original.co_filename, 'exec')
                cls.compiled[name] = (original, output, rebuilt)
            except Exception as error:
                cls.compiled[name] = error

    def test_observable_behaviour(self):
        for name, compiled in self.compiled.items():
            with self.subTest(case=name):
                self.assertIsInstance(compiled, tuple, str(compiled))
            if not isinstance(compiled, tuple):
                continue
            original, output, rebuilt = compiled
            for data in INPUTS:
                with self.subTest(case=name, data=data):
                    self.assertEqual(execute(original, data), execute(rebuilt, data), output)

    def test_generator_close_unwinds_all_blocks(self):
        for name in ('generator_with_finally', 'async_generator_with_finally', 'yield_from_finally'):
            for action in (True, 'throw'):
                with self.subTest(case=name, action=action):
                    original, output, rebuilt = self.compiled[name]
                    self.assertEqual(execute(original, [1, 2], action),
                                     execute(rebuilt, [1, 2], action), output)

    def test_rewriter_is_repeatable(self):
        def shape(instructions):
            return [(ins.offset, ins.opname, repr(ins.argval), ins.block_id,
                     ins.protected_by, ins.synthetic_loop_exit) for ins in instructions]

        for name, source in SOURCES.items():
            code = compile(source, '<flow:%s>' % name, 'exec')
            function = next(value for value in code.co_consts if inspect.iscode(value))
            with self.subTest(case=name):
                rewriter = self.rewriter(function)
                self.assertEqual(shape(rewriter.run()), shape(rewriter.run()))

    def test_reported_boom_structure(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'boom.py')
        with open(path, encoding='utf-8') as handle:
            source = handle.read()
        output = self.backend.decompile(compile(source, '<boom>', 'exec'))
        self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(output)), output)

    def test_source_structure(self):
        # These shapes are unambiguous with source spans, including the copy of
        # a break return whose value must only be loaded after finally runs.
        for name in ('copied_break_return', 'return_before_finally',
                     'except_else_returns', 'except_else_return_only',
                     'loop_with_nested_finally', 'retry_and_following_loop'):
            with self.subTest(case=name):
                compiled = self.compiled[name]
                self.assertIsInstance(compiled, tuple, str(compiled))
                self.assertEqual(ast.dump(ast.parse(SOURCES[name])),
                                 ast.dump(ast.parse(compiled[1])), compiled[1])

    def test_region_ownership(self):
        for name, source in SOURCES.items():
            pending = [compile(source, '<flow:%s>' % name, 'exec')]
            while pending:
                code = pending.pop()
                pending.extend(value for value in code.co_consts if inspect.iscode(value))
                with self.subTest(case=name, code=code.co_name):
                    instructions = self.rewriter(code).run()
                    if not instructions:
                        continue
                    setups = [ins for ins in instructions if ins.opname in (
                        'SETUP_FINALLY', 'SETUP_EXCEPT', 'SETUP_WITH', 'SETUP_ASYNC_WITH')]
                    offsets = {ins.offset for ins in instructions}
                    self.assertTrue(all(ins.argval in offsets for ins in setups))
                    regions = self.analyzer(instructions).regions()
                    self.assertEqual(len(regions), len(setups))
                    for region in regions:
                        self.assertIsNotNone(region.body_end)
                        self.assertLessEqual(region.body_start, region.body_end)
                        self.assertLessEqual(region.body_end, region.handlers[0][0])
                        owner = instructions[region.setup_index].block_id
                        for pop in region.body_pops + region.exit_pops:
                            self.assertIn(instructions[pop].block_id, (None, owner))


def run():
    """Report this suite in tests/run.py without changing its legacy counts."""
    if not (3, 11) <= sys.version_info[:2] <= (3, 13):
        return []
    from tests.test_roundtrip import Result
    rows = []

    class Results(unittest.TestResult):
        def __init__(self):
            super().__init__()
            self._current_diffs = []

        def startTest(self, test):
            self._current_diffs = []
            super().startTest(test)

        def addSubTest(self, test, subtest, error):
            if error is not None:
                self._current_diffs.append('%s: %s' % (subtest, error[1]))
            super().addSubTest(test, subtest, error)

        def addFailure(self, test, error):
            self._current_diffs.append('%s: %s' % (test, error[1]))
            super().addFailure(test, error)

        def addError(self, test, error):
            self._current_diffs.append('%s: %s' % (test, error[1]))
            super().addError(test, error)

        def stopTest(self, test):
            diffs = [diff[:2000] for diff in self._current_diffs]
            rows.append(Result('modern_' + test._testMethodName.removeprefix('test_'), not diffs, diffs))
            super().stopTest(test)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ModernControlFlowTests)
    suite.run(Results())
    if not rows:
        rows.append(Result('modern_suite', False, ['suite did not run']))
    return rows


if __name__ == '__main__':
    unittest.main(verbosity=2)
