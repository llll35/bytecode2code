"""Regressions from the user's original D:\\build\\test-pyc comparison artifacts.

The three archived .pyc files are byte-for-byte copies, not newly compiled
substitutes. Other versions exercise the same source and protocol scenarios.
"""
import ast
import asyncio
import contextlib
import hashlib
import importlib
import importlib.util
import io
import json
import marshal
from pathlib import Path
import sys
import textwrap
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tests.equivalence import compare

ARCHIVES = {
    (3, 9): ('comparison_py39_feat39.pyc', 'comparison_feat39.py', 'sync'),
    (3, 14): ('comparison_py314_t314c.pyc', 'comparison_t312c.py', 'async'),
    (3, 15): ('comparison_py315_t315c.pyc', 'comparison_t312c.py', 'async'),
}


def read_pyc(path):
    data = Path(path).read_bytes()
    if data[:4] != importlib.util.MAGIC_NUMBER:
        raise ValueError('requires the interpreter matching ' + str(path))
    return marshal.loads(data[16:])


def describe(error, depth=0):
    context = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    return (type(error).__name__, str(error),
            describe(context, depth + 1) if context is not None and depth < 4 else None)


def injected(name, options):
    choice = options.get(name)
    if choice == 'missing':
        raise FileNotFoundError(name + ' failed')
    if choice == 'value':
        raise ValueError(name + ' failed')
    if choice == 'exit':
        raise LookupError(name + ' failed')
    if choice == 'cancel':
        raise asyncio.CancelledError(name + ' cancelled')


class ExitResult:
    def __init__(self, events, options):
        self.events, self.options = events, options

    def __bool__(self):
        self.events.append('exit.bool')
        injected('truth', self.options)
        return self.options.get('suppress', False)


def sync_scenarios():
    cases = ({}, {'open': 'missing'}, {'enter': 'missing'}, {'enter': 'value'},
             {'read': 'missing'}, {'read': 'value'}, {'read': 'value', 'suppress': True},
             {'exit': 'missing'}, {'exit': 'exit'}, {'read': 'value', 'exit': 'exit'},
             {'read': 'value', 'truth': 'value'}, {'truth': 'value'})
    for options in cases:
        for cleanup_error in (False, True):
            yield dict(options, cleanup_error=cleanup_error)


def observe_sync(code, options):
    namespace, events = {}, []
    exec(code, namespace)

    class File:
        def __enter__(self):
            events.append('enter')
            injected('enter', options)
            return self

        def read(self):
            events.append('read')
            injected('read', options)
            return 'payload'

        def __exit__(self, kind, error, traceback):
            events.append(('exit', kind.__name__ if kind else None, str(error) if error else None))
            injected('exit', options)
            return ExitResult(events, options)

    def open_file(path):
        events.append(('open', path))
        injected('open', options)
        return File()

    def print_value(*values):
        events.append(('finally', values))
        if options['cleanup_error']:
            raise RuntimeError('finally failed')

    namespace.update(open=open_file, print=print_value)
    try:
        outcome = 'return', namespace['risky']()
    except BaseException as error:
        outcome = 'raise', describe(error)
    return outcome, events


def async_scenarios():
    return ({}, {'enter': 'value'}, {'body': 'value'}, {'body': 'cancel'},
            {'body': 'value', 'suppress': True}, {'body': 'cancel', 'suppress': True},
            {'exit': 'exit'}, {'body': 'value', 'exit': 'exit'},
            {'body': 'value', 'truth': 'value'}, {'truth': 'value'})


def observe_async(code, options, function='main', returned=False):
    namespace, events, managers = {}, [], []
    exec(code, namespace)

    class Manager:
        locked = False

        async def __aenter__(self):
            events.append('enter.start')
            await asyncio.sleep(0)
            injected('enter', options)
            self.locked = True
            events.append('enter.done')
            return 'token'

        async def __aexit__(self, kind, error, traceback):
            events.append(('exit.start', kind.__name__ if kind else None, str(error) if error else None))
            await asyncio.sleep(0)
            self.locked = False
            events.append('exit.done')
            injected('exit', options)
            return ExitResult(events, options)

    def factory():
        events.append('factory')
        manager = Manager()
        managers.append(manager)
        return manager

    async def work(value):
        events.append(('body.start', value))
        await asyncio.sleep(0)
        injected('body', options)
        events.append('body.done')
        return 'payload' if returned else None

    namespace['asyncio'] = SimpleNamespace(Lock=factory, sleep=work)
    try:
        coroutine = namespace[function](factory, work) if function != 'main' else namespace['main']()
        outcome = 'return', asyncio.run(coroutine)
    except BaseException as error:
        outcome = 'raise', describe(error)
    return outcome, events, [manager.locked for manager in managers]


@unittest.skipUnless((3, 9) <= sys.version_info[:2] <= (3, 15), 'requires an in-tree backend')
class ComparisonRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = importlib.import_module('py%d%dDecompiler' % sys.version_info[:2])
        manifest = json.loads((ROOT / 'tests' / 'samples' / 'comparison_manifest.json').read_text(encoding='utf-8'))
        for sample in manifest['files']:
            path = ROOT / 'tests' / 'samples' / sample['file']
            if hashlib.sha256(path.read_bytes()).hexdigest() != sample['sha256']:
                raise AssertionError('original bytecode fixture changed: ' + str(path))

    def roundtrip(self, source, original=None):
        source = textwrap.dedent(source).lstrip()
        original = original or compile(source, '<comparison_regression>', 'exec')
        output = self.backend.decompile(original)
        rebuilt = compile(output, original.co_filename, 'exec')
        self.assertEqual(compare(original, rebuilt), [], output)
        self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(output)), output)
        return original, rebuilt, output

    def archived(self):
        spec = ARCHIVES.get(sys.version_info[:2])
        if spec is None:
            self.skipTest('archived failures target 3.9, 3.14 and 3.15')
        pyc, source, kind = spec
        original = read_pyc(ROOT / 'tests' / 'samples' / pyc)
        text = (ROOT / 'tests' / 'repro' / source).read_text(encoding='utf-8')
        return original, text, kind

    def test_original_archived_pyc_structure(self):
        original, source, _ = self.archived()
        self.roundtrip(source, original)

    def test_original_archived_pyc_behavior(self):
        original, _, kind = self.archived()
        output = self.backend.decompile(original)
        rebuilt = compile(output, original.co_filename, 'exec')
        scenarios = sync_scenarios() if kind == 'sync' else async_scenarios()
        observe = observe_sync if kind == 'sync' else observe_async
        for options in scenarios:
            with self.subTest(options=options):
                self.assertEqual(observe(original, options), observe(rebuilt, options), output)

    def test_with_return_inside_except_finally(self):
        source = (ROOT / 'tests' / 'repro' / 'comparison_feat39.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        risky = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'risky')
        original, rebuilt, output = self.roundtrip(ast.unparse(risky))
        for options in sync_scenarios():
            with self.subTest(options=options):
                self.assertEqual(observe_sync(original, options), observe_sync(rebuilt, options), output)

    def test_async_with_awaited_entry_body_and_exit(self):
        for returned in (False, True):
            with self.subTest(returned=returned):
                body = 'return await work(token)' if returned else 'await work(token)'
                source = textwrap.dedent('''
                    async def f(factory, work):
                        async with factory() as token:
                            %s
                ''' % body).lstrip()
                if not returned:
                    source += "    await work('after')\n"
                original, rebuilt, output = self.roundtrip(source)
                for options in async_scenarios():
                    self.assertEqual(observe_async(original, options, 'f', returned),
                                     observe_async(rebuilt, options, 'f', returned), output)

    @unittest.skipUnless(sys.version_info[:2] == (3, 12), 'original .pyc files target 3.12')
    def test_original_return_statement_artifacts(self):
        for pyc, source, name, values in (
                ('comparison_py312_hello.pyc', 'comparison_hello312.py', 'greet', (None, '', 'world', 42)),
                ('comparison_py312_t312b.pyc', 'comparison_t312b.py', 'sign', (-2, 0, 3, None, 'bad'))):
            with self.subTest(pyc=pyc):
                original = read_pyc(ROOT / 'tests' / 'samples' / pyc)
                text = (ROOT / 'tests' / 'repro' / source).read_text(encoding='utf-8')
                original, rebuilt, output = self.roundtrip(text, original)
                observations = []
                for code in (original, rebuilt):
                    namespace, captured = {}, io.StringIO()
                    with contextlib.redirect_stdout(captured):
                        exec(code, namespace)
                    results = []
                    for value in values:
                        try:
                            result = 'return', namespace[name](value)
                        except Exception as error:
                            result = 'raise', describe(error)
                        results.append(result)
                    observations.append((captured.getvalue(), results))
                self.assertEqual(observations[0], observations[1], output)

    @unittest.skipUnless(sys.version_info >= (3, 11), 'requires source columns')
    def test_return_statements_and_genuine_conditional_expressions(self):
        for source in ('''
            def f(x):
                if x > 0:
                    return 1
                elif x < 0:
                    return -1
                return 0
        ''', '''
            def f(x):
                return 1 if x > 0 else -1 if x < 0 else 0
        ''', '''
            def f(x, a, b):
                return (
                    a
                    if x
                    else b
                )
        '''):
            with self.subTest(source=source):
                self.roundtrip(source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
