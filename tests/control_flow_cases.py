"""Control-flow combinations compiled by each 3.11--3.13 interpreter."""

import textwrap


SOURCES = {
    "copied_break_return": """
        def f(data, events):
            result = 0
            for value in data:
                try:
                    if value == 'stop':
                        break
                    result += work(value)
                finally:
                    result += 100
                    events.append(result)
            else:
                result += 1000
            return result
    """,
    "return_before_finally": """
        def f(data, events):
            result = 1
            for value in data:
                try:
                    if value == 'stop':
                        return result
                    result += work(value)
                finally:
                    result += 100
                    events.append(result)
            return result
    """,
    "except_else_returns": """
        def f(data, events):
            try:
                result = work(data[0])
            except ValueError as error:
                events.append(str(error))
                return -1
            except TypeError:
                raise
            else:
                events.append('else')
                return result
            finally:
                events.append('finally')
    """,
    "except_else_return_only": """
        def f(data, events):
            try:
                result = work(data[0])
            except ValueError as error:
                events.append(str(error))
            else:
                return result
    """,
    "loop_with_nested_finally": """
        def f(data, events):
            result = []
            for value in data:
                with cm('outer') as a, cm('inner') as b:
                    try:
                        if value == 'skip':
                            continue
                        if value == 'stop':
                            break
                        try:
                            result.append(work(value))
                        except ValueError as error:
                            events.append(str(error))
                            continue
                        finally:
                            try:
                                events.append('deep')
                            finally:
                                events.append('deepest')
                    finally:
                        events.append('mid')
            else:
                events.append('finished')
            try:
                return result
            finally:
                events.append('cleanup')
    """,
    "with_suppression": """
        def f(data, events):
            result = []
            for value in data:
                try:
                    with cm('outer'), cm('suppress', True):
                        result.append(work(value))
                        events.append('body')
                    events.append('after-with')
                except TypeError as error:
                    events.append(str(error))
                    continue
                finally:
                    events.append('finally')
                events.append('after-try')
            return result
    """,
    "return_from_multi_with": """
        def f(data, events):
            with cm('outer') as a, cm('inner') as b:
                try:
                    return work(data[0]) + a + b
                finally:
                    events.append('finally')
    """,
    "finally_overrides_exit": """
        def f(data, events):
            try:
                for value in data:
                    if value == 'stop':
                        return 10
                    events.append(work(value))
            except ValueError as error:
                events.append(str(error))
                raise
            finally:
                events.append('finally')
                if len(data) > 2:
                    return 99
            return 0
    """,
    "break_from_except": """
        def f(data, events):
            result = 0
            for value in data:
                try:
                    result += work(value)
                except ValueError as error:
                    events.append(str(error))
                    break
                except TypeError:
                    continue
                finally:
                    result += 100
                    events.append(result)
            else:
                result += 1000
            return result
    """,
    "finally_break_continue": """
        def f(data, events):
            result = []
            for value in data:
                try:
                    result.append(work(value))
                finally:
                    events.append('finally')
                    if value == 'skip':
                        continue
                    if value == 'stop':
                        break
                    events.append('after-guard')
            else:
                events.append('else')
            return result
    """,
    "while_try_else": """
        def f(data, events):
            index = 0
            result = 0
            while index < len(data):
                value = data[index]
                index += 1
                try:
                    if value == 'skip':
                        continue
                    if value == 'stop':
                        break
                    result += work(value)
                except ValueError as error:
                    events.append(str(error))
                else:
                    events.append('success')
                finally:
                    result += 100
            else:
                events.append('exhausted')
            return result
    """,
    "retry_and_following_loop": """
        def f(data, events):
            iterator = iter(data)
            while True:
                value = next(iterator)
                try:
                    result = work(value)
                    if result < 0:
                        result = -result
                    break
                except ValueError as error:
                    events.append(str(error))
            for value in data:
                try:
                    events.append(work(value))
                except (ValueError, TypeError) as error:
                    events.append(str(error))
            return result
    """,
    "nested_loops_else": """
        def f(data, events):
            result = 0
            for outer in data:
                for inner in data:
                    try:
                        if inner == 'skip':
                            continue
                        if inner == 'stop':
                            break
                        result += work(inner)
                    except ValueError:
                        break
                    finally:
                        events.append('inner')
                else:
                    events.append('inner-else')
                    continue
                events.append('outer-tail')
            else:
                events.append('outer-else')
            return result
    """,
    "independent_nested_handlers": """
        def f(data, events):
            result = 0
            try:
                try:
                    result = work(data[0])
                except ValueError as error:
                    events.append(str(error))
                    raise RuntimeError('wrapped') from error
                finally:
                    events.append('inner')
            except RuntimeError as error:
                events.append(str(error))
            finally:
                events.append('outer')
            try:
                result += work(data[-1])
            except TypeError as error:
                events.append(str(error))
            return result
    """,
    "finally_nested_in_handler": """
        def f(data, events):
            try:
                return work(data[0])
            except ValueError as error:
                try:
                    events.append(str(error))
                    return -1
                finally:
                    events.append('handler-finally')
            finally:
                events.append('outer-finally')
    """,
    "comprehension_in_try": """
        def f(data, events):
            try:
                result = [work(value) for value in data if value != 'skip']
            except ValueError as error:
                events.append(str(error))
                result = []
            finally:
                events.append('finally')
            return result
    """,
    "async_with_for": """
        async def f(data, events):
            result = []
            async for value in aiter_values(data):
                async with acm('outer') as a, acm('inner') as b:
                    try:
                        if value == 'skip':
                            continue
                        if value == 'stop':
                            break
                        result.append(await awork(value))
                    except ValueError as error:
                        events.append(str(error))
                    finally:
                        events.append('finally')
            else:
                events.append('else')
            return result
    """,
    "async_return_finally": """
        async def f(data, events):
            async with acm('outer'), acm('inner'):
                try:
                    return await awork(data[0])
                finally:
                    events.append('finally')
    """,
    "generator_with_finally": """
        def f(data, events):
            for value in data:
                with cm('outer'):
                    try:
                        if value == 'skip':
                            continue
                        if value == 'stop':
                            break
                        yield work(value)
                    except ValueError as error:
                        events.append(str(error))
                    finally:
                        events.append('finally')
            else:
                events.append('else')
    """,
    "exception_group_finally": """
        def f(data, events):
            result = []
            try:
                try:
                    raise ExceptionGroup('group', [ValueError('v'), TypeError('t')])
                except* ValueError as error:
                    result.append(str(error))
                except* TypeError as error:
                    events.append(str(error))
            finally:
                events.append('finally')
            return result
    """,
    "finally_raises": """
        def f(data, events):
            try:
                return work(data[0])
            finally:
                events.append('finally')
                raise RuntimeError('finally-error')
    """,
    "finally_returns_none": """
        def f(data, events):
            try:
                return work(data[0])
            finally:
                events.append('finally')
                return None
    """,
    "finally_returns_expression": """
        def f(data, events):
            try:
                return work(data[0])
            finally:
                events.append('finally')
                return len(data) + 100
    """,
    "finally_raise_conditional": """
        def f(data, events):
            try:
                result = work(data[0])
            except ValueError:
                result = -1
            finally:
                events.append('finally')
                if len(data) > 1:
                    raise KeyError('finally-error')
            return result
    """,
    "nested_finally_return_timing": """
        def f(data, events):
            result = 1
            try:
                try:
                    result += work(data[0])
                    return result
                finally:
                    result += 100
                    events.append(result)
            finally:
                result += 1000
                events.append(result)
    """,
    "break_none_tail": """
        def f(data, events):
            for value in data:
                try:
                    if value == 'stop':
                        break
                    events.append(work(value))
                finally:
                    events.append('finally')
            else:
                events.append('else')
    """,
    "with_exit_raises": """
        def f(data, events):
            try:
                with cm('outer'), cm('exit-error'):
                    return work(data[0])
            except RuntimeError as error:
                events.append(str(error))
                return -1
            finally:
                events.append('finally')
    """,
    "with_enter_raises": """
        def f(data, events):
            try:
                with cm('outer'), cm('enter-error'):
                    events.append(work(data[0]))
            except RuntimeError as error:
                events.append(str(error))
            finally:
                events.append('finally')
            return 3
    """,
    "except_attribute_types": """
        def f(data, events):
            try:
                return work(data[0])
            except errors.ValueError as error:
                events.append(str(error))
                return -1
            except (errors.TypeError, IndexError):
                events.append('other')
                return -2
            finally:
                events.append('finally')
    """,
    "except_binding_is_cleared": """
        def f(data, events):
            error = 'old'
            try:
                result = work(data[0])
            except ValueError as error:
                events.append(str(error))
                result = -1
            try:
                events.append(error)
            except UnboundLocalError:
                events.append('cleared')
            return result
    """,
    "async_nested_loops": """
        async def f(data, events):
            result = []
            async for outer in aiter_values(data):
                async for value in aiter_values(data):
                    async with acm('outer'):
                        try:
                            if value == 'skip':
                                continue
                            if value == 'stop':
                                break
                            result.append(await awork(value))
                        except ValueError as error:
                            events.append(str(error))
                            break
                        finally:
                            events.append('finally')
                else:
                    events.append('inner-else')
                    continue
                events.append('outer-tail')
            else:
                events.append('outer-else')
            return result
    """,
    "async_finally_break_continue": """
        async def f(data, events):
            result = []
            async for value in aiter_values(data):
                try:
                    result.append(await awork(value))
                finally:
                    events.append('finally')
                    if value == 'skip':
                        continue
                    if value == 'stop':
                        break
                    events.append('tail')
            else:
                events.append('else')
            return result
    """,
    "yield_from_finally": """
        def f(data, events):
            try:
                yield from data
            finally:
                events.append('finally')
    """,
    "exception_group_partial": """
        def f(data, events):
            try:
                raise ExceptionGroup('group', [ValueError('v'), TypeError('t')])
            except* ValueError as error:
                events.append(str(error))
            finally:
                events.append('finally')
    """,
    "exception_group_handler_raises": """
        def f(data, events):
            try:
                raise ExceptionGroup('group', [ValueError('v'), TypeError('t')])
            except* ValueError as error:
                events.append(str(error))
                raise OSError('replacement') from None
            except* TypeError:
                events.append('type-handled')
            finally:
                events.append('finally')
    """,
    "exception_group_nested_try": """
        def f(data, events):
            result = []
            try:
                raise ExceptionGroup('group', [ValueError('v'), TypeError('t')])
            except* ValueError as error:
                with cm('outer'):
                    try:
                        result.append(work(data[0]))
                    except (ValueError, IndexError):
                        events.append(str(error))
                    finally:
                        events.append('inner')
            except* TypeError:
                events.append('type-handled')
            finally:
                events.append('finally')
            return result
    """,
    "exception_group_pass": """
        def f(data, events):
            try:
                raise ExceptionGroup('group', [ValueError('v'), TypeError('t')])
            except* (ValueError, TypeError):
                pass
            finally:
                events.append('finally')
            return 3
    """,
    "async_return_after_continue": """
        async def f(data, events):
            async for value in aiter_values(data):
                if value == 'skip':
                    continue
                return await awork(value)
            else:
                events.append('else')
            return -1
    """,
    "async_immediate_break": """
        async def f(data, events):
            async for value in aiter_values(data):
                break
            else:
                events.append('else')
            return len(data)
    """,
    "async_generator_with_finally": """
        async def f(data, events):
            async for value in aiter_values(data):
                async with acm('outer'):
                    try:
                        if value == 'skip':
                            continue
                        if value == 'stop':
                            break
                        yield work(value)
                    except ValueError as error:
                        events.append(str(error))
                    finally:
                        events.append('finally')
            else:
                events.append('else')
    """,
    "raise_only_finally_raises": """
        def f(data, events):
            try:
                raise ValueError('body')
            finally:
                events.append('finally')
                raise RuntimeError('replacement')
    """,
    "raise_only_finally_returns": """
        def f(data, events):
            try:
                raise ValueError('body')
            finally:
                events.append('finally')
                return None
    """,
    "bare_reraise_finally": """
        def f(data, events):
            try:
                return work(data[0])
            except ValueError:
                try:
                    raise
                finally:
                    events.append('finally')
    """,
    "finally_nested_except": """
        def f(data, events):
            try:
                return work(data[0])
            finally:
                try:
                    events.append(work(data[-1]))
                except ValueError as error:
                    events.append(str(error))
    """,
    "conditional_try_boundary": """
        def f(data, events):
            if len(data) > 1:
                try:
                    value = work(data[0])
                    if value < 0:
                        raise ValueError('negative')
                except:
                    raise RuntimeError('wrapped')
    """,
}

SOURCES = {name: textwrap.dedent(source).lstrip() for name, source in SOURCES.items()}


def _exit_matrix():
    """Vary loop, abrupt exit and enclosing cleanup independently."""
    sources = {}
    exits = dict(break_='break', continue_='continue', return_='return result',
                 raise_="raise RuntimeError('stop')")
    for loop in ('for', 'while', 'async'):
        for action, statement in exits.items():
            for wrapper in ('plain', 'with', 'finally'):
                name = 'matrix_%s_%s_%s' % (loop, action.rstrip('_'), wrapper)
                awaited = 'await awork(value)' if loop == 'async' else 'work(value)'
                suite = ("try:\n"
                         "    if value == 'skip':\n"
                         "        continue\n"
                         "    if value == 'stop':\n"
                         "        %s\n"
                         "    result += %s\n"
                         "except ValueError as error:\n"
                         "    events.append(str(error))\n"
                         "    continue\n"
                         "finally:\n"
                         "    result += 100\n"
                         "    events.append(result)\n") % (statement, awaited)
                if wrapper == 'with':
                    context = ("async with acm('outer'), acm('inner'):\n" if loop == 'async'
                               else "with cm('outer'), cm('inner'):\n")
                    suite = context + textwrap.indent(suite, '    ')
                elif wrapper == 'finally':
                    suite = ("try:\n" + textwrap.indent(suite, '    ') + "finally:\n"
                             "    result += 1000\n    events.append('outer-finally')\n")
                source = ('async def' if loop == 'async' else 'def') + " f(data, events):\n    result = 0\n"
                if loop == 'while':
                    source += ("    index = 0\n    while index < len(data):\n"
                               "        value = data[index]\n        index += 1\n")
                else:
                    source += ("    async for value in aiter_values(data):\n" if loop == 'async'
                               else "    for value in data:\n")
                source += textwrap.indent(suite, '        ')
                source += "    else:\n        events.append('else')\n    return result\n"
                sources[name] = source
    return sources


SOURCES.update(_exit_matrix())

INPUTS = ((), (0,), (1,), (-1, 0, 2), (1, 2, 3), ('stop',), (1, 'stop', 2), ('skip', 2),
          ('bad', 2), (1, 'bad', 2), ('type', 2), ('bad', 'skip', 'stop', 3))
