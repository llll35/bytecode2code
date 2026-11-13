#!/usr/bin/env python3
"""Adversarial round trips: patterns, short-circuit guards, cleanup and exits.

    python tripwire.py                    # all seven embedded interpreters
    python tripwire.py --version 3.14 --verbose
    python tripwire.py --case mapping_nested --json results.json

Each case must preserve its AST, the existing recursive code-object comparison,
and observable behavior. Fixtures record subject calls, truth tests, attribute
reads, sequence/mapping access, exceptions and finally ordering. No networking
or user files are touched. The samples are strings so Python 3.9 can run the
driver and explicitly skip syntax it does not support.
"""
import argparse
import ast
from collections.abc import Mapping, Sequence
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
CASES = {
    'mixed_and': ((3, 10), '''
        def f(value, left, middle, right):
            match value:
                case [a, b] if left(a) and (middle(b) or right(a)):
                    return a + b
                case _:
                    return None
    '''),
    'mixed_or': ((3, 10), '''
        def f(value, left, middle, right):
            match value:
                case [a, b] if left(a) or (middle(b) and right(a)):
                    return a + b
                case _:
                    return None
    '''),
    'guard_lines': ((3, 10), '''
        def f(value, left, right):
            match value:
                case [a, b] if (
                    left(a)
                    and right(b)
                ):
                    return a + b
                case _:
                    return None
    '''),
    'capture_guard': ((3, 10), '''
        def f(value, gate):
            match value:
                case n if gate(n):
                    return n + 1
                case _:
                    return None
    '''),
    'wildcard_guard': ((3, 10), '''
        def f(value, gate):
            match value:
                case 0:
                    return 'zero'
                case _ if gate():
                    return 'guard'
                case _:
                    return 'other'
    '''),
    'literal_sequence': ((3, 10), '''
        def f(value):
            match value:
                case [0, item]:
                    return item
                case _:
                    return None
    '''),
    'nested_sequence': ((3, 10), '''
        def f(value):
            match value:
                case [first, [second, *tail]]:
                    return first + second + len(tail)
                case _:
                    return None
    '''),
    'empty_sequence': ((3, 10), '''
        def f(value):
            match value:
                case []:
                    return 'empty'
                case [first, *tail]:
                    return first + len(tail)
                case _:
                    return None
    '''),
    'class_literals': ((3, 10), '''
        def f(value):
            match value:
                case Point(0, y, label='hot'):
                    return y
                case _:
                    return None
    '''),
    'mapping_nested': ((3, 10), '''
        def f(value):
            match value:
                case {'kind': 'sum', 'payload': [head, *tail], **rest}:
                    return head + len(tail) + len(rest)
                case _:
                    return None
    '''),
    'sequence_alias': ((3, 10), '''
        def f(value):
            match value:
                case [a, b] as pair if a > b:
                    return pair
                case _:
                    return None
    '''),
    'same_line_cases': ((3, 10), '''
        def f(value):
            match value:
                case 0: return 'zero'
                case 1: return 'one'
                case _:
                    return 'other'
    '''),
    'loop_finally': ((3, 10), '''
        def f(values, gate, events):
            for value in values:
                try:
                    match value:
                        case [a, b] if gate(a) and (gate(b) or gate(-a)):
                            continue
                        case 0:
                            break
                        case _:
                            events.append(value)
                finally:
                    events.append('finally')
            events.append('after')
            return events
    '''),
    'subject_lines': ((3, 10), '''
        def f(subject):
            match subject(
                'key'
            ):
                case 0:
                    return 'zero'
                case _:
                    return 'other'
    '''),
    'ordinary_multiline_if': ((3, 9), '''
        def f(value, events):
            if (value ==
                    0):
                events.append('zero')
            else:
                events.append('other')
            events.append('after')
            return events
    '''),
    'return_finally': ((3, 9), '''
        def f(work, cleanup):
            try:
                return work()
            finally:
                cleanup()
    '''),
}


class _Events(list):
    def __init__(self, cleanup_error=False):
        super().__init__()
        self.cleanup_error = cleanup_error

    def append(self, value):
        if len(self) >= 1024:
            raise RuntimeError('observation budget exceeded')
        super().append(value)
        if self.cleanup_error and value == 'finally':
            raise RuntimeError('cleanup failed')


class _Truth:
    def __init__(self, events, label, result):
        self.events, self.label, self.result = events, label, result

    def __bool__(self):
        self.events.append(('bool', self.label))
        if self.result == 'raise':
            raise ValueError('truth failed: ' + self.label)
        return self.result


class _Point:
    __match_args__ = ('x', 'y')

    def __init__(self, values, events, error=None):
        self.values, self.events, self.error = values, events, error

    def __getattr__(self, name):
        self.events.append(('attr', name))
        if self.error == name + ':attribute':
            raise AttributeError(name)
        if self.error == name + ':value':
            raise ValueError('attribute failed: ' + name)
        if name not in self.values:
            raise AttributeError(name)
        return self.values[name]


class _Sequence(Sequence):
    def __init__(self, values, events):
        self.values, self.events = values, events

    def __len__(self):
        self.events.append('sequence.len')
        return len(self.values)

    def __getitem__(self, index):
        self.events.append(('sequence.item', index))
        return self.values[index]


class _Mapping(Mapping):
    def __init__(self, values, events, broken=None):
        self.values, self.events, self.broken = values, events, broken

    def __len__(self):
        self.events.append('mapping.len')
        return len(self.values)

    def __iter__(self):
        self.events.append('mapping.iter')
        return iter(self.values)

    def __getitem__(self, key):
        self.events.append(('mapping.item', key))
        if key == self.broken:
            raise ValueError('mapping failed: ' + key)
        return self.values[key]


class _Integer(int):
    def __new__(cls, value, events, broken=False):
        result = super().__new__(cls, value)
        result.events, result.broken = events, broken
        return result

    def __eq__(self, other):
        self.events.append(('eq', int(self), other))
        if self.broken:
            raise ValueError('equality failed')
        return int.__eq__(self, other)

    __hash__ = int.__hash__


def _fixture(value, events):
    if isinstance(value, tuple) and value:
        if value[0] == '@point':
            return _Point(dict(zip(('x', 'y', 'label'), value[1:4])), events, value[4])
        if value[0] == '@sequence':
            return _Sequence([_fixture(v, events) for v in value[1]], events)
        if value[0] == '@mapping':
            return _Mapping({k: _fixture(v, events) for k, v in value[1].items()}, events, value[2])
        if value[0] == '@int':
            return _Integer(value[1], events, value[2])
    if isinstance(value, (list, tuple)):
        return type(value)(_fixture(v, events) for v in value)
    if isinstance(value, dict):
        return {k: _fixture(v, events) for k, v in value.items()}
    return value


def _freeze(value):
    if isinstance(value, (_Sequence, _Mapping, _Point)):
        return type(value).__name__, _freeze(value.values)
    if isinstance(value, _Integer):
        return int(value)
    if isinstance(value, (list, tuple)):
        return type(value).__name__, tuple(_freeze(v) for v in value)
    if isinstance(value, dict):
        return 'dict', tuple((k, _freeze(v)) for k, v in value.items())
    return value


def _exception(error, depth=0):
    context = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    return (type(error).__name__, str(error),
            _exception(context, depth + 1) if context is not None and depth < 4 else None)


def scenarios(name):
    """Fresh inputs per run; every recorded truth test may also raise."""
    if name in ('mixed_and', 'mixed_or', 'guard_lines'):
        for value in ([2, 3], ('@sequence', [2, 3]), None):
            for decisions in itertools.product((False, True, 'raise'), repeat=3):
                yield value, {'decisions': dict(zip(('left', 'middle', 'right'), decisions))}
    elif name in ('capture_guard', 'wildcard_guard'):
        for value in (0, 1, -2, None, 'text'):
            for result in (False, True, 'raise'):
                yield value, {'decisions': {'gate': result}}
    elif name == 'literal_sequence':
        for value in (None, [], [0], [0, 7], (0, 8), [1, 9], [True, 10], b'01',
                      [('@int', 0, False), 11], [('@int', 0, True), 11], ('@sequence', [0, 12])):
            yield value, {}
    elif name == 'nested_sequence':
        for value in (None, [], [1, []], [1, 2], [1, [2]], [1, [2, 3, 4]],
                      (1, (2, 3)), [1, '23'], ['bad', [2]],
                      ('@sequence', [1, ('@sequence', [2, 3])])):
            yield value, {}
    elif name == 'empty_sequence':
        for value in (None, [], (), b'', '', [1], [1, 2, 3], ['bad'], ('@sequence', []),
                      ('@sequence', [2, 3])):
            yield value, {}
    elif name == 'class_literals':
        for value in (None, (0, 2, 'hot'), ('@point', 0, 2, 'hot', None),
                      ('@point', 1, 2, 'hot', None), ('@point', 0, 2, 'cold', None),
                      ('@point', 0, 2, 'hot', 'label:attribute'),
                      ('@point', 0, 2, 'hot', 'y:value')):
            yield value, {}
    elif name == 'mapping_nested':
        for value in (None, {}, {'kind': 'sum'}, {'kind': 'other', 'payload': [2, 3]},
                      {'kind': 'sum', 'payload': []}, {'kind': 'sum', 'payload': '23'},
                      {'kind': 'sum', 'payload': [2, 3], 'extra': 4},
                      {'kind': 'sum', 'payload': ['bad']},
                      ('@mapping', {'kind': 'sum', 'payload': [2, 3], 'extra': 4}, None),
                      ('@mapping', {'kind': 'sum', 'payload': [2, 3]}, 'payload')):
            yield value, {}
    elif name == 'sequence_alias':
        for value in (None, [1, 2], [2, 1], (2, 1), [2, 2], ('@sequence', [3, 1])):
            yield value, {}
    elif name in ('same_line_cases', 'subject_lines', 'ordinary_multiline_if'):
        for value in (0, 1, 2, None, '0', ('@int', 0, False), ('@int', 0, True)):
            yield value, {}
        if name == 'subject_lines':
            yield 0, {'subject_error': True}
    elif name == 'loop_finally':
        for values in ([], [0, 9], [[2, 3], 0, 9], [7, [2, 3], 8], [[2, 3], [4, 5]]):
            for decisions in ({2: False}, {2: True, 3: False, -2: True}, {2: 'raise'}):
                for cleanup_error in (False, True):
                    yield values, {'by_arg': decisions, 'cleanup_error': cleanup_error}
    elif name == 'return_finally':
        for work_error, cleanup_error in itertools.product((False, True), repeat=2):
            yield 7, {'work_error': work_error, 'cleanup_error': cleanup_error}
    else:
        raise ValueError('missing scenarios for ' + name)


def observe(code, name, input_value, options):
    events = _Events(options.get('cleanup_error', False))
    value = _fixture(input_value, events)
    namespace = {'Point': _Point}
    exec(code, namespace)

    def decision(label):
        def call(*args):
            events.append(('call', label, _freeze(args)))
            result = options.get('decisions', {}).get(label, True)
            if label == 'gate' and args:
                result = options.get('by_arg', {}).get(args[0], result)
            return _Truth(events, label, result)
        return call

    def subject(key):
        events.append(('subject', key))
        if options.get('subject_error'):
            raise ValueError('subject failed')
        return value

    def work():
        events.append('work')
        if options.get('work_error'):
            raise ValueError('work failed')
        return value

    def cleanup():
        events.append('finally')

    if name in ('mixed_and', 'mixed_or'):
        args = (value, decision('left'), decision('middle'), decision('right'))
    elif name == 'guard_lines':
        args = (value, decision('left'), decision('right'))
    elif name in ('capture_guard', 'wildcard_guard'):
        args = (value, decision('gate'))
    elif name == 'subject_lines':
        args = (subject,)
    elif name == 'loop_finally':
        args = (value, decision('gate'), events)
    elif name == 'ordinary_multiline_if':
        args = (value, events)
    elif name == 'return_finally':
        args = (work, cleanup)
    else:
        args = (value,)
    try:
        result = namespace['f'](*args)
        outcome = ('return', _freeze(result), result is value if name == 'sequence_alias' else None)
    except BaseException as error:
        outcome = ('raise', _exception(error))
    return outcome, _freeze(list(events))


def check_case(name):
    minimum, snippet = CASES[name]
    row = {'name': name, 'status': 'SKIP', 'diffs': [], 'scenarios': 0, 'output': ''}
    if sys.version_info[:2] < minimum:
        row['diffs'] = ['needs Python %d.%d+' % minimum]
        return row
    source = textwrap.dedent(snippet).lstrip()
    try:
        original = compile(source, '<tripwire:' + name + '>', 'exec')
        backend = importlib.import_module('py%d%dDecompiler' % sys.version_info[:2])
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', SyntaxWarning)
            output = backend.decompile(original)
            rebuilt = compile(output, original.co_filename, 'exec')
        row['output'] = output
    except Exception as error:
        row['status'] = 'CRASH'
        row['diffs'] = [type(error).__name__ + ': ' + str(error)]
        return row
    if ast.dump(ast.parse(source)) != ast.dump(ast.parse(output)):
        row['diffs'].append('source AST differs')
    row['diffs'].extend(compare(original, rebuilt))
    for index, (value, options) in enumerate(scenarios(name)):
        expected = observe(original, name, value, options)
        actual = observe(rebuilt, name, value, options)
        row['scenarios'] += 1
        if expected != actual:
            row['diffs'].append('behavior #%d: %r != %r' % (index, expected, actual))
    row['status'] = 'DIFF' if row['diffs'] else 'OK'
    return row


def run_here(names):
    version = '%d.%d' % sys.version_info[:2]
    if version not in SUPPORTED:
        return {'version': version, 'results': [], 'error': 'no supported backend'}
    return {'version': version, 'results': [check_case(name) for name in names]}


def _run_child(version, names):
    interpreter = ROOT / 'embed_python' / ('python-' + version) / 'python.exe'
    if not interpreter.is_file():
        return {'version': version, 'results': [], 'error': 'embedded interpreter missing'}
    command = [str(interpreter), str(Path(__file__).resolve()), '--one', '--json', '-']
    for name in names:
        command.extend(('--case', name))
    try:
        completed = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True,
                                   encoding='utf-8', errors='replace', timeout=180)
        group = json.loads(completed.stdout)
        if completed.returncode and all(r['status'] in ('OK', 'SKIP') for r in group['results']):
            group['error'] = 'child exited %d: %s' % (completed.returncode, completed.stderr[-1000:])
        return group
    except (subprocess.TimeoutExpired, ValueError, OSError) as error:
        return {'version': version, 'results': [], 'error': type(error).__name__ + ': ' + str(error)}


def failed(group):
    return bool(group.get('error')) or any(r['status'] not in ('OK', 'SKIP') for r in group['results'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--one', action='store_true', help='only use the running interpreter')
    parser.add_argument('--version', choices=SUPPORTED, help='only use this embedded interpreter')
    parser.add_argument('--case', action='append', choices=tuple(CASES), help='only run this case (repeatable)')
    parser.add_argument('--verbose', '-v', action='store_true', help='include failing emitted source')
    parser.add_argument('--json', metavar='PATH', help='save full results; - emits JSON only')
    args = parser.parse_args(argv)
    names = args.case or list(CASES)
    if args.one:
        groups = [run_here(names)]
    else:
        versions = (args.version,) if args.version else SUPPORTED
        with ThreadPoolExecutor(max_workers=len(versions)) as pool:
            groups = list(pool.map(lambda version: _run_child(version, names), versions))
    status = int(any(failed(group) for group in groups))
    payload = groups[0] if args.one else groups
    if args.json == '-':
        print(json.dumps(payload, ensure_ascii=True))
        return status
    if args.json:
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding='utf-8')
    total = passed = observations = 0
    for group in groups:
        print('Python ' + group['version'])
        if group.get('error'):
            print('  [ERROR] ' + group['error'])
        for row in group['results']:
            print('  [%-5s] %-25s %s' % (row['status'], row['name'], '; '.join(row['diffs'][:2])))
            if row['status'] != 'SKIP':
                total += 1
                passed += row['status'] == 'OK'
                observations += row['scenarios']
            if args.verbose and row['status'] in ('DIFF', 'CRASH'):
                for diff in row['diffs'][2:]:
                    print('      ' + diff)
                print(row['output'])
    print('tripwire: %d/%d cases passed; %d behavioral scenarios checked' % (passed, total, observations))
    return status


if __name__ == '__main__':
    sys.exit(main())
