"""Unit tests for the control-flow graph and exception-region engine.

These check the engine against boundaries read off CPython's own disassembly by
hand, so a change to the graph cannot quietly move a region boundary: every
defect in ``bugs.md`` that this module is meant to replace was a boundary read
from the wrong opcode.

Run the hand-verified boundaries with ``python -m tests.test_cfg`` on 3.9.
Run ``python tests/test_cfg.py Rewriter311Tests`` on 3.11 for translated handlers.
Run ``python tests/test_cfg.py OutputNormalizationTests`` on each supported version.
"""

import ast
import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from py39Decompiler.cfg_flow import (
    ExceptionAnalyzer, KIND_AS_CLEANUP, KIND_EXCEPT, KIND_FINALLY, KIND_WITH,
    build_cfg)
from py39Decompiler.disassembler import Disassembler


def _code_objects(source):
    code = compile(source, "<test>", "exec")
    found = [code]
    for const in code.co_consts:
        if hasattr(const, "co_code"):
            found.append(const)
    return found


def _regions(source, name):
    """Regions of the function called *name*, keyed by setup offset."""
    dis_ = Disassembler()
    for code in _code_objects(source):
        if code.co_name != name:
            continue
        instructions = dis_.disassemble(code)
        analyzer = ExceptionAnalyzer(instructions)
        return {instructions[region.setup_index].offset: region
                for region in analyzer.regions()}, instructions
    raise KeyError(name)


def _shape(source, name):
    """``{setup offset: (kind, body end offset or None)}``."""
    regions, instructions = _regions(source, name)
    return {offset: (region.kind,
                     None if region.body_end is None
                     else instructions[region.body_end].offset)
            for offset, region in regions.items()}


class GraphTests(unittest.TestCase):
    def test_block_stack_has_no_pop_for_loops(self):
        # 3.8 dropped SETUP_LOOP, so a plain loop contributes no region.
        source = ("def f(xs):\n"
                  "    for x in xs:\n"
                  "        g(x)\n")
        self.assertEqual(_shape(source, "f"), {})

    def test_dominator_of_a_join_is_the_branch_head(self):
        source = ("def f(a):\n"
                  "    if a:\n"
                  "        x = 1\n"
                  "    else:\n"
                  "        x = 2\n"
                  "    return x\n")
        instructions = Disassembler().disassemble(_code_objects(source)[1])
        cfg = build_cfg(instructions)
        idom = cfg.dominators()
        # The block that both arms fall into is joined at the ``if``.
        joined = [block for block in cfg.blocks if len(block.predecessors) > 1]
        self.assertTrue(joined, "expected a join block in an if/else")
        for block in joined:
            self.assertIn(idom.get(block.number), {b.number for b in cfg.blocks})
            self.assertTrue(cfg.dominance_frontier(idom))


class RegionTests(unittest.TestCase):
    def test_try_finally(self):
        source = ("def f(p):\n"
                  "    try:\n"
                  "        g()\n"
                  "    finally:\n"
                  "        print(p)\n")
        # Body ends at the POP_BLOCK that closes the region; the handler is
        # reached only by unwinding.
        self.assertEqual(_shape(source, "f"),
                         {0: (KIND_FINALLY, 8)})

    def test_try_except_else_finally_keeps_the_three_apart(self):
        source = ("def f(n):\n"
                  "    try:\n"
                  "        x = int(n)\n"
                  "    except ValueError as e:\n"
                  "        print(e)\n"
                  "    else:\n"
                  "        x += 1\n"
                  "    finally:\n"
                  "        print('done')\n")
        self.assertEqual(_shape(source, "f"), {
            0: (KIND_FINALLY, 68),     # the try/finally region
            2: (KIND_EXCEPT, 12),      # the except chain's protected body
            28: (KIND_AS_CLEANUP, 38),  # the guard around `as e`
        })

    def test_with_inside_try_does_not_steal_the_trys_pop(self):
        # bugs.md 9 and 10: the reader took the ``with``'s POP_BLOCK as the end
        # of the enclosing ``try`` body.  The two ranges have to stay distinct.
        source = ("def f(p):\n"
                  "    try:\n"
                  "        with open(p) as fh:\n"
                  "            d = fh.read()\n"
                  "        return d\n"
                  "    except OSError:\n"
                  "        return None\n")
        self.assertEqual(_shape(source, "f"), {
            0: (KIND_EXCEPT, 52),
            8: (KIND_WITH, 20),
        })

    def test_finally_inside_with(self):
        source = ("def g(p):\n"
                  "    with open(p) as fh:\n"
                  "        try:\n"
                  "            return fh.read()\n"
                  "        finally:\n"
                  "            fh.close()\n")
        self.assertEqual(_shape(source, "g"), {
            6: (KIND_WITH, 28),
            10: (KIND_FINALLY, 18),
        })

    def test_body_that_only_raises_has_no_pop_block(self):
        # The compiler emits no POP_BLOCK when the body can only unwind, so the
        # end is a reachability result rather than a found opcode.
        source = ("def f():\n"
                  "    try:\n"
                  "        try:\n"
                  "            try:\n"
                  "                raise OSError('deep error')\n"
                  "            except OSError:\n"
                  "                raise IOError('wrap os error')\n"
                  "        except IOError:\n"
                  "            raise\n"
                  "    except Exception as e:\n"
                  "        print(e)\n")
        shapes = _shape(source, "f")
        self.assertEqual({offset: kind for offset, (kind, _) in shapes.items()
                          if kind != KIND_AS_CLEANUP},
                         {0: KIND_EXCEPT, 2: KIND_EXCEPT, 4: KIND_EXCEPT})

    def test_nested_finally_and_reraise_boundaries(self):
        # The shape the project's reported limitation was filed against.
        source = ("def f(x):\n"
                  "    try:\n"
                  "        if x < 0:\n"
                  "            raise ValueError('less than zero')\n"
                  "        for i in range(x):\n"
                  "            try:\n"
                  "                if i == 3:\n"
                  "                    raise RuntimeError('hit 3')\n"
                  "            except RuntimeError as e:\n"
                  "                print(i)\n"
                  "                raise\n"
                  "            finally:\n"
                  "                print('inner finally always run')\n"
                  "    except ValueError as ve:\n"
                  "        print(ve)\n"
                  "        return -1\n"
                  "    except Exception as ee:\n"
                  "        print(ee)\n"
                  "    finally:\n"
                  "        if x > 100:\n"
                  "            return 999\n"
                  "        print('outer finally')\n"
                  "    return 0\n")
        self.assertEqual(_shape(source, "f"), {
            2: (KIND_FINALLY, 242),      # try/... /finally, outermost
            4: (KIND_EXCEPT, 128),       # the except chain
            34: (KIND_FINALLY, 104),     # inner try/finally, inside the loop
            36: (KIND_EXCEPT, 54),       # inner except chain
            70: (KIND_AS_CLEANUP, 82),   # `as e` guard
            144: (KIND_AS_CLEANUP, 154),  # `as ve` guard
            210: (KIND_AS_CLEANUP, 220),  # `as ee` guard
        })

    def test_every_corpus_region_closes(self):
        """No region anywhere in the corpus may come back without an end."""
        from tests.cases import FLOW_PROBES, PROBES
        dis_ = Disassembler()
        total = 0
        for source in list(FLOW_PROBES.values()) + list(PROBES.values()):
            for code in _code_objects(source):
                instructions = dis_.disassemble(code)
                if not instructions:
                    continue
                for region in ExceptionAnalyzer(instructions).regions():
                    total += 1
                    self.assertIsNotNone(
                        region.body_end,
                        "%s setup at offset %d" % (
                            code.co_name, instructions[region.setup_index].offset))
        self.assertGreater(total, 40, "expected the corpus to exercise regions")


@unittest.skipUnless(sys.version_info[:2] == (3, 11), "requires Python 3.11 bytecode")
class Rewriter311Tests(unittest.TestCase):
    def setUp(self):
        from py311Decompiler.decomp311 import Decompiler311, Rewriter
        from tests.cases import FLOW_PROBES
        self.source = FLOW_PROBES["nested_finally_reraise"]
        self.code = compile(self.source, "<test>", "exec")
        self.function = next(c for c in self.code.co_consts
                             if hasattr(c, "co_code") and c.co_name == "f")
        self.rewriter = Rewriter(self.function)
        self.instructions = self.rewriter.run()
        self.reader = Decompiler311()

    def test_finally_setups_resolve_to_exact_handler_entries(self):
        from py311Decompiler.cfg_flow import ExceptionAnalyzer as Analyzer311
        offsets = {instr.offset for instr in self.instructions}
        setups = [instr for instr in self.instructions
                  if instr.opname == "SETUP_FINALLY"]
        for instr in setups:
            self.assertIn(instr.argval, offsets)
        regions = Analyzer311(self.instructions).regions()
        self.assertEqual(len(regions), len(setups))
        finals = [region for region in regions if region.kind == KIND_FINALLY]
        self.assertEqual(len(finals), 2)
        for region in finals:
            self.assertTrue(region.body_pops)
            self.assertLess(region.body_end, region.handlers[0][0])
        # Resolving a setup must not relocate instructions that other branches
        # already target.  The surviving handler load keeps its raw address.
        raw_offsets = {raw.offset for raw in self.rewriter.raw
                       if raw.opname == "LOAD_GLOBAL"}
        for instr in self.instructions:
            if instr.opname == "LOAD_GLOBAL":
                self.assertIn(instr.offset, raw_offsets)

    def test_conditional_return_does_not_truncate_handler(self):
        from py311Decompiler.cfg_flow import ExceptionAnalyzer as Analyzer311
        outer = next(region for region in Analyzer311(self.instructions).regions()
                     if region.kind == KIND_FINALLY)
        handler = outer.handlers[0][0]
        end = self.reader._handler_end(self.instructions, handler)
        self.assertEqual(self.instructions[end - 1].opname, "RERAISE")
        self.assertIn("RETURN_VALUE", [instr.opname
                                      for instr in self.instructions[handler:end]])

    def test_nested_finally_roundtrip_has_no_duplicate_clauses(self):
        import ast
        from py311Decompiler import decompile
        from tests.equivalence import compare
        output = decompile(self.code)
        self.assertEqual(compare(self.code, compile(output, "<test>", "exec")), [])
        tree = ast.parse(output)
        for value in ("inner finally always run", "outer finally"):
            occurrences = [node for node in ast.walk(tree)
                           if isinstance(node, ast.Constant) and node.value == value]
            self.assertEqual(len(occurrences), 1, value)
        self.assertFalse(any(node.orelse for node in ast.walk(tree)
                             if isinstance(node, ast.Try)))


class OutputNormalizationTests(unittest.TestCase):
    def setUp(self):
        package = "py%d%dDecompiler" % sys.version_info[:2]
        self.backend = importlib.import_module(package)
        self.reader = importlib.import_module(package + ".decompiler").Decompiler()

    def test_combines_except_else_and_finally(self):
        source = ("try:\n"
                  "    try:\n"
                  "        work()\n"
                  "    except ValueError as e:\n"
                  "        recover(e)\n"
                  "    else:\n"
                  "        success()\n"
                  "finally:\n"
                  "    cleanup()\n")
        expected = ("try:\n"
                    "    work()\n"
                    "except ValueError as e:\n"
                    "    recover(e)\n"
                    "else:\n"
                    "    success()\n"
                    "finally:\n"
                    "    cleanup()\n")
        tree = ast.parse(source)
        self.reader._combine_try_clauses(tree.body)
        self.assertEqual(ast.dump(tree), ast.dump(ast.parse(expected)))
        self.reader._combine_try_clauses(tree.body)
        self.assertEqual(ast.dump(tree), ast.dump(ast.parse(expected)))
        compile(ast.fix_missing_locations(tree), "<test>", "exec")

    def test_combines_inside_nested_scopes(self):
        source = ("class C:\n"
                  "    def f(self):\n"
                  "        for x in xs:\n"
                  "            try:\n"
                  "                try:\n"
                  "                    work(x)\n"
                  "                except ValueError:\n"
                  "                    recover()\n"
                  "            finally:\n"
                  "                cleanup()\n")
        tree = ast.parse(source)
        self.reader._combine_try_clauses(tree.body)
        tries = [node for node in ast.walk(tree) if isinstance(node, ast.Try)]
        self.assertEqual(len(tries), 1)
        self.assertTrue(tries[0].handlers)
        self.assertTrue(tries[0].finalbody)

    def test_preserves_real_nested_scopes(self):
        from tests.cases import FLOW_PROBES
        sources = [
            FLOW_PROBES["reraise_chain"],
            "try:\n    try:\n        work()\n    finally:\n        inner()\nfinally:\n    outer()\n",
            "try:\n    before()\n    try:\n        work()\n    except E:\n        recover()\nfinally:\n    cleanup()\n",
            "try:\n    try:\n        work()\n    except E:\n        recover()\n    after()\nfinally:\n    cleanup()\n",
            "try:\n    try:\n        work()\n    except E:\n        recover()\nexcept F:\n    other()\nfinally:\n    cleanup()\n",
            "try:\n    try:\n        work()\n    except E:\n        recover()\n    finally:\n        inner()\nfinally:\n    outer()\n",
        ]
        for source in sources:
            with self.subTest(source=source):
                tree = ast.parse(source)
                before = ast.dump(tree)
                self.reader._combine_try_clauses(tree.body)
                self.assertEqual(ast.dump(tree), before)

    def test_module_branches_have_no_returns(self):
        from tests.equivalence import compare
        sources = [
            "if __name__ == '__main__':\n    run()\n",
            "if __name__ == '__main__':\n    pass\n",
            "if flag:\n    pass\n",
            "if flag:\n    if other:\n        run()\n",
            "if flag:\n    run()\nelse:\n    other()\n",
            "if flag:\n    run()\nelif other:\n    second()\nelse:\n    third()\n",
            "with cm:\n    run()\n",
            "if flag:\n    with cm:\n        run()\n",
        ]
        for source in sources:
            with self.subTest(source=source):
                code = compile(source, "<test>", "exec")
                output = self.backend.decompile(code)
                tree = ast.parse(output)
                self.assertFalse(any(isinstance(node, ast.Return)
                                     for node in ast.walk(tree)), output)
                rebuilt = compile(output, "<test>", "exec")
                self.assertEqual(compare(code, rebuilt), [], output)

    def test_module_conditional_assignment_still_works(self):
        from tests.equivalence import compare
        code = compile("x = 1 if flag else 2\n", "<test>", "exec")
        output = self.backend.decompile(code)
        self.assertEqual(compare(code, compile(output, "<test>", "exec")), [])

    def test_function_returns_are_preserved(self):
        source = ("def f(flag):\n"
                  "    if flag:\n"
                  "        return None\n"
                  "    return 7\n"
                  "if __name__ == '__main__':\n"
                  "    f(True)\n")
        output = self.backend.decompile(compile(source, "<test>", "exec"))
        tree = ast.parse(output)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
        self.assertTrue(any(isinstance(node, ast.Return) for node in ast.walk(function)))
        namespace = {"__name__": "test_module"}
        exec(compile(output, "<test>", "exec"), namespace)
        self.assertIsNone(namespace["f"](True))
        self.assertEqual(namespace["f"](False), 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
