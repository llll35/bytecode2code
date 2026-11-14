#!/usr/bin/env python3
"""Stress ordinary mixed Boolean branches and loops on CPython 3.9--3.15.

python ambush.py
python ambush.py --version 3.10 --verbose
python ambush.py --json ambush-results.json

Checks source AST, the unchanged recursive code-object comparison, and actual
short-circuit/loop/exception behavior. Truth objects change over time and may
raise; bounded event recording and child-process timeouts prevent hangs.
"""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import importlib
import itertools
import json
from pathlib import Path
import subprocess
import sys
import textwrap
import warnings

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tests.equivalence import compare

SUPPORTED = ('3.9', '3.10', '3.11', '3.12', '3.13', '3.14', '3.15')


def _branch(condition):
    return '''
        def f(a, b, c, events):
            if %s:
                events.append('hit')
            else:
                events.append('miss')
            events.append('after')
            return events
    ''' % condition


def _loop(condition):
    return '''
        def f(a, b, c, events):
            while %s:
                events.append('body')
            events.append('after')
            return events
    ''' % condition


CASES = {
    'if_and_or': _branch('a and (b or c)'),
    'if_or_and': _branch('a or (b and c)'),
    'if_left_or': _branch('(a or b) and c'),
    'if_left_and': _branch('(a and b) or c'),
    'if_negated_term': _branch('a and (not b or c)'),
    'if_finally': '''
        def f(a, b, c, events):
            try:
                if a and (b or c):
                    events.append('hit')
                else:
                    events.append('miss')
            except ValueError as error:
                events.append(('caught', str(error)))
            finally:
                events.append('cleanup')
            events.append('after')
            return events
    ''',
    'while_and_or': _loop('a and (b or c)'),
    'while_or_and': _loop('a or (b and c)'),
    'while_break_else': '''
        def f(a, b, c, events):
            turns = 0
            while a and (b or c):
                events.append('body')
                turns += 1
                if turns == 2:
                    break
            else:
                events.append('exhausted')
            events.append('after')
            return events
    ''',
    'while_finally': '''
        def f(a, b, c, events):
            while a and (b or c):
                try:
                    events.append('body')
                finally:
                    events.append('cleanup')
            events.append('after')
            return events
    ''',
}


class Events(list):
    def __init__(self, cleanup_error=False):
        super().__init__()
        self.cleanup_error = cleanup_error

    def append(self, value):
        if len(self) >= 256:
            raise RuntimeError('observation budget exceeded')
        super().append(value)
        if self.cleanup_error and value == 'cleanup':
            raise RuntimeError('cleanup failed')


class Switch:
    def __init__(self, name, stream, events):
        self.name, self.stream, self.events = name, tuple(stream), events
        self.count = 0

    def __bool__(self):
        value = self.stream[self.count] if self.count < len(self.stream) else False
        self.events.append(('test', self.name, self.count, value))
        self.count += 1
        if value == 'raise':
            raise ValueError('truth failed: ' + self.name)
        return value


def _exception(error, depth=0):
    context = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    return (type(error).__name__, str(error),
            _exception(context, depth + 1) if context is not None and depth < 4 else None)


def scenarios(name):
    streams = [tuple((value,) for value in values)
               for values in itertools.product((False, True, 'raise'), repeat=3)]
    streams.extend((
        ((True, True, False), (True, False, True), (False, True)),
        ((True, True, True, False), (True, True, True), (False,)),
        ((True, 'raise'), (False, True), (True, False)),
        ((False, True), (True, 'raise'), (True, False)),
    ))
    for stream in streams:
        for cleanup_error in ((False, True) if 'finally' in name else (False,)):
            yield stream, cleanup_error


def observe(code, stream, cleanup_error=False):
    namespace, events = {}, Events(cleanup_error)
    exec(code, namespace)
    values = [Switch(name, values, events) for name, values in zip(('a', 'b', 'c'), stream)]
    try:
        result = namespace['f'](*values, events)
        outcome = 'return', list(result)
    except BaseException as error:
        outcome = 'raise', _exception(error)
    return outcome, list(events)


def check_case(name):
    source = textwrap.dedent(CASES[name]).lstrip()
    row = {'name': name, 'status': 'CRASH', 'diffs': [], 'scenarios': 0, 'output': ''}
    try:
        original = compile(source, '<ambush:' + name + '>', 'exec')
        backend = importlib.import_module('py%d%dDecompiler' % sys.version_info[:2])
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', SyntaxWarning)
            row['output'] = backend.decompile(original)
            rebuilt = compile(row['output'], original.co_filename, 'exec')
        if ast.dump(ast.parse(source)) != ast.dump(ast.parse(row['output'])):
            row['diffs'].append('source AST differs')
        row['diffs'].extend(compare(original, rebuilt))
        for index, (stream, cleanup_error) in enumerate(scenarios(name)):
            expected, actual = observe(original, stream, cleanup_error), observe(rebuilt, stream, cleanup_error)
            row['scenarios'] += 1
            if expected != actual:
                row['diffs'].append('behavior #%d: %r != %r' % (index, expected, actual))
        row['status'] = 'DIFF' if row['diffs'] else 'OK'
    except Exception as error:
        row['diffs'].append(type(error).__name__ + ': ' + str(error))
    return row


def run_here(names):
    version = '%d.%d' % sys.version_info[:2]
    if version not in SUPPORTED:
        return {'version': version, 'results': [], 'error': 'no supported backend'}
    return {'version': version, 'results': [check_case(name) for name in names]}


def failed(group):
    return bool(group.get('error')) or any(row['status'] != 'OK' for row in group['results'])


def _child(version, names):
    executable = ROOT / 'embed_python' / ('python-' + version) / 'python.exe'
    command = [str(executable), str(Path(__file__).resolve()), '--one', '--json', '-']
    for name in names:
        command.extend(('--case', name))
    try:
        completed = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True,
                                   encoding='utf-8', errors='replace', timeout=180)
        group = json.loads(completed.stdout)
        if completed.returncode and not failed(group):
            group['error'] = 'child failed: ' + completed.stderr[-1000:]
        return group
    except (subprocess.TimeoutExpired, ValueError, OSError) as error:
        return {'version': version, 'results': [], 'error': type(error).__name__ + ': ' + str(error)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--one', action='store_true')
    parser.add_argument('--version', choices=SUPPORTED)
    parser.add_argument('--case', action='append', choices=tuple(CASES))
    parser.add_argument('--verbose', '-v', action='store_true')
    parser.add_argument('--json', metavar='PATH', help='save complete results; - emits JSON only')
    args = parser.parse_args(argv)
    names = args.case or list(CASES)
    if args.one:
        groups = [run_here(names)]
    else:
        versions = (args.version,) if args.version else SUPPORTED
        with ThreadPoolExecutor(max_workers=len(versions)) as pool:
            groups = list(pool.map(lambda version: _child(version, names), versions))
    status = int(any(failed(group) for group in groups))
    payload = groups[0] if args.one else groups
    if args.json == '-':
        print(json.dumps(payload))
        return status
    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding='utf-8')
    passed = total = count = 0
    for group in groups:
        print('Python ' + group['version'])
        if group.get('error'):
            print('  [ERROR] ' + group['error'])
        for row in group['results']:
            total += 1
            passed += row['status'] == 'OK'
            count += row['scenarios']
            print('  [%-5s] %-22s %s' % (row['status'], row['name'], '; '.join(row['diffs'][:2])))
            if args.verbose and row['status'] != 'OK':
                print('\n'.join(row['diffs'][2:]))
                print(row['output'])
    print('ambush: %d/%d cases passed; %d behavioral scenarios checked' % (passed, total, count))
    return status


if __name__ == '__main__':
    sys.exit(main())
