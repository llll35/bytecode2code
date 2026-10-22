# Implementation Plan: Control Flow Reconstruction Bug Fixes

## Overview

This task plan addresses four control flow reconstruction bugs in the Python bytecode decompiler's exception handling (`try`/`except`/`finally`/`else`) support across Python versions 3.9, 3.10, 3.11, and 3.12. The bugs cause incorrect decompilation where code after `try`-`except` blocks is swallowed, collapsed, or improperly handled.

The implementation follows the design document's architecture:
1. Add new data structures for tracking saved instructions and retargeted jumps
2. Implement new methods: `_redirect_handler_exits`, `_save_tail_for_merge`, `_merge_offset`, `_restore_break_continue`
3. Modify existing methods: `_process_instruction`, `_emit_statements`, `_collect_finally_body`
4. Add version detection for Python 3.12-specific handling

All tasks reference specific line numbers and method names from `decompiler.py`.

## Tasks

- [ ] 1. Set up new data structures for exception handling control flow reconstruction
  - [ ] 1.1 Add `_tails_at_merge` dictionary to `__init__` (line 186)
    - Store saved tail instructions keyed by merge offset for Python 3.12
    - _Requirements: 1.1, 2.1_
  
  - [ ] 1.2 Add `_retarget` dictionary to `__init__` (line 186)
    - Track retargeted jumps (original_offset -> new_target)
    - _Requirements: 1.1, 1.2_
  
  - [ ] 1.3 Add `_drops` set to `__init__` (line 186)
    - Track dropped instruction offsets to avoid double-emission
    - _Requirements: 1.1, 1.2_
  - _Checkpoint: Ensure all instance variables are initialized correctly_

- [ ] 2. Implement `_redirect_handler_exits` method
  - [ ] 2.1 Create method signature and docstring (after line 750, after `_collect_finally_body`)
    - Method: `_redirect_handler_exits(self, instructions: List[Instruction]) -> None`
    - Purpose: Retarget handler exit jumps from backward to forward, save tail instructions
    - _Requirements: 1.1, 1.2, 2.1_
  
  - [ ] 2.2 Iterate through exception entries from `co_exceptiontable`
    - For each entry, find handler_start (entry.target) and RERAISE
    - _Requirements: 1.1, 2.1_
  
  - [ ] 2.3 For each jump instruction before RERAISE in handler:
    - If backward jump to entry.end: retarget to merge + save tail (Python 3.12)
    - If backward jump elsewhere: retarget to merge directly
    - _Requirements: 1.1, 1.2, 2.1_
  
  - [ ] 2.4 Store retargeted jumps in `_retarget` dict
    - Key: original jump offset, Value: new target offset
    - _Requirements: 1.2, 2.1_
  - _Checkpoint: Verify handler exit jumps are correctly redirected_

- [ ] 3. Implement `_save_tail_for_merge` method
  - [ ] 3.1 Create method signature and docstring (after `_redirect_handler_exits`)
    - Method: `_save_tail_for_merge(self, instructions: List[Instruction], tail_start: int, merge_offset: int) -> None`
    - Purpose: Collect and save tail instructions for later emission at merge point
    - _Requirements: 1.1, 2.1_
  
  - [ ] 3.2 Find handler_start (first instruction after tail_start that's part of handler)
    - _Requirements: 1.1, 2.1_
  
  - [ ] 3.3 Collect all instructions with offset in [tail_start, handler_start)
    - Store in `_tails_at_merge[merge_offset]`
    - _Requirements: 1.1, 2.1_
  
  - [ ] 3.4 Add each collected instruction's offset to `_drops` set
    - Prevent double-emission of saved tail instructions
    - _Requirements: 1.1, 2.1_
  - _Checkpoint: Verify tail instructions are saved correctly_

- [ ] 4. Implement `_merge_offset` helper method
  - [ ] 4.1 Create method signature and docstring (after `_save_tail_for_merge`)
    - Method: `_merge_offset(self, instructions: List[Instruction], handler_start_idx: int, target_offset: int) -> int`
    - Purpose: Calculate offset just past all handlers belonging to a try block
    - _Requirements: 1.1, 1.2, 2.1_
  
  - [ ] 4.2 Find all exception entries that belong to the same try block
    - Use exception table entries to identify related handlers
    - _Requirements: 1.1, 2.1_
  
  - [ ] 4.3 Find the handler entry with the largest end offset
    - _Requirements: 1.1, 2.1_
  
  - [ ] 4.4 Return index of first instruction after that handler's end
    - _Requirements: 1.1, 2.1_
  - _Checkpoint: Verify merge offset calculation is correct_

- [ ] 5. Implement `_restore_break_continue` method
  - [ ] 5.1 Create method signature and docstring (after `_merge_offset`)
    - Method: `_restore_break_continue(self, instructions: List[Instruction], pop_idx: int, handler_start_idx: int, target_offset: int, try_end_idx: int) -> List[ast.stmt]`
    - Purpose: Detect and restore `break` and `continue` statements at try block boundaries
    - _Requirements: 1.2, 2.2_
  
  - [ ] 5.2 Check for POP_BLOCK + unconditional forward jump (break)
    - Starting at try_end_idx + 1
    - _Requirements: 1.2, 2.2_
  
  - [ ] 5.3 Detect forward jump = ast.Break()
    - Target > jump instruction offset
    - _Requirements: 1.2, 2.2_
  
  - [ ] 5.4 Detect backward jump = handled by `_continue_over_handler` (not in this method)
    - Backward jumps are already handled by existing code
    - _Requirements: 1.2, 2.2_
  
  - [ ] 5.5 Return list with ast.Break() if break detected, empty list otherwise
    - _Requirements: 1.2, 2.2_
  - _Checkpoint: Verify break/continue detection works correctly_

- [ ] 6. Modify `_process_instruction` POP_BLOCK handler (line ~1500)
  - [ ] 6.1 After parsing handlers with `_parse_except_handlers`, check if redirection needed
    - Call `_needs_redirect` helper if needed
    - _Requirements: 1.1, 1.2, 2.1_
  
  - [ ] 6.2 If handler exit redirection needed, call `_redirect_handler_exits(instructions)`
    - Apply retargeting before continuing
    - _Requirements: 1.1, 1.2, 2.1_
  
  - [ ] 6.3 Handle saved tail emission for Python 3.12
    - Use `_tails_at_merge` to emit saved instructions at merge points
    - _Requirements: 1.1, 2.1_
  
  - [ ] 6.4 Update skip_to calculation for exception blocks
    - Account for retargeted jumps in jump target calculation
    - _Requirements: 1.1, 1.2, 2.1_
  - _Checkpoint: Verify POP_BLOCK handler correctly processes all exception types_

- [ ] 7. Modify `_emit_statements` method (line ~1200)
  - [ ] 7.1 Check for saved tail instructions at current position
    - Before normal statement emission
    - _Requirements: 1.1, 2.1_
  
  - [ ] 7.2 Emit saved tail instructions at merge points
    - If current offset in `_tails_at_merge`, emit each saved instruction
    - Convert 3.12 instructions to 3.9 form if needed
    - _Requirements: 1.1, 2.1_
  
  - [ ] 7.3 Update handled_ranges tracking
    - Mark saved tail instructions as handled to avoid re-emission
    - _Requirements: 1.1, 2.1_
  - _Checkpoint: Verify saved tail instructions are emitted at correct positions_

- [ ] 8. Modify `_collect_finally_body` method (line ~950)
  - [ ] 8.1 Detect nested SETUP_FINALLY within finally body
    - Scan collected body for SETUP_FINALLY opcodes
    - _Requirements: 1.4, 2.4_
  
  - [ ] 8.2 Split collection at nested SETUP_FINALLY
    - Collect outer finally up to nested SETUP_FINALLY
    - _Requirements: 1.4, 2.4_
  
  - [ ] 8.3 Collect inner finally recursively
    - Recursively process nested finally blocks
    - _Requirements: 1.4, 2.4_
  
  - [ ] 8.4 Combine outer and inner finally bodies correctly
    - Preserve hierarchical structure in AST
    - _Requirements: 1.4, 2.4_
  - _Checkpoint: Verify nested finally blocks are handled correctly_

- [ ] 9. Add version detection for Python 3.12-specific handling
  - [ ] 9.1 Import sys module (line 10, after other imports)
    - Already imported, verify availability
    - _Requirements: 1.1, 1.3_
  
  - [ ] 9.2 Create helper method `_is_python_312_plus() -> bool`
    - Return sys.version_info >= (3, 12)
    - _Requirements: 1.1, 1.3_
  
  - [ ] 9.3 Update `_redirect_handler_exits` to check Python version
    - Only apply Python 3.12 tail placement logic for version >= 3.12
    - _Requirements: 1.1, 1.3, 2.1_
  
  - [ ] 9.4 Update `_save_tail_for_merge` to check Python version
    - Only save tail for Python 3.12+ where tail is placed before handler
    - _Requirements: 1.1, 1.3, 2.1_
  - _Checkpoint: Verify version detection correctly applies 3.12-specific logic_

- [ ] 10. Test bug fixes for Python 3.12 module-level try/except (D1)
  - [ ] 10.1 Create test case with module-level try/except + break/continue
    - Test case at `debug/archive/debug_312_try_except_break.py`
    - _Requirements: 1.1, 2.1_
  
  - [ ] 10.2 Verify saved tail instructions are emitted at merge point
    - Check `_tails_at_merge` contains correct instructions
    - _Requirements: 1.1, 2.1_
  
  - [ ] 10.3 Verify subsequent definitions are not swallowed
    - Run decompiler on test bytecode
    - Verify all definitions appear in output
    - _Requirements: 1.1, 2.1_
  - _Checkpoint: Verify D1 bug is fixed for Python 3.12_

- [ ] 11. Test break/continue restoration (D2)
  - [ ] 11.1 Create test cases for break/continue in try blocks (Python 3.9-3.12)
    - Test files: `debug/archive/debug_break_in_try.py`, `debug/archive/debug_continue_in_try.py`
    - _Requirements: 1.2, 2.2_
  
  - [ ] 11.2 Verify `_restore_break_continue` detects break statements
    - Check try_end_idx + 1 for POP_BLOCK + forward jump
    - _Requirements: 1.2, 2.2_
  
  - [ ] 11.3 Verify AST contains ast.Break() after try/except
    - Parse decompiled output to AST
    - Check for ast.Break() node after try/except
    - _Requirements: 1.2, 2.2_
  
  - [ ] 11.4 Verify loop exit boundary is correct
    - Check loop structure in decompiled code
    - _Requirements: 1.2, 2.2_
  - _Checkpoint: Verify D2 bug is fixed for all Python versions_

- [ ] 12. Test else clause preservation (D4)
  - [ ] 12.1 Create test cases for try/except/else (Python 3.1)
    - Test file: `debug/archive/debug_else_clause.py`
    - _Requirements: 1.3, 3.3_
  
  - [ ] 12.2 Verify `_recover_else_clause` correctly identifies else boundaries
    - Check try_end_idx + 1 jump target
    - _Requirements: 1.3, 3.3_
  
  - [ ] 12.3 Verify else clause is included in orelse field of Try node
    - Check Try node has correct orelse content
    - _Requirements: 1.3, 3.3_
  
  - [ ] 12.4 Verify subsequent code is not swallowed
    - Check decompiled output for all statements after try/except/else
    - _Requirements: 1.3, 3.3_
  - _Checkpoint: Verify D4 bug is fixed for else clause preservation_

- [ ] 13. Test nested finally structure preservation (D3)
  - [ ] 13.1 Create test cases for deeply nested finally (Python 3.11-3.12)
    - Test file: `debug/archive/debug_nested_finally.py`
    - _Requirements: 1.4, 2.4_
  
  - [ ] 13.2 Verify `_collect_finally_body` detects nested SETUP_FINALLY
    - Check for nested finally blocks during collection
    - _Requirements: 1.4, 2.4_
  
  - [ ] 13.3 Verify hierarchical structure preserved in AST
    - Check nested TryFinally nodes in AST
    - _Requirements: 1.4, 2.4_
  
  - [ ] 13.4 Verify no collapse of finally blocks
    - Run decompiler and compare with original source
    - _Requirements: 1.4, 2.4_
  - _Checkpoint: Verify D3 bug is fixed for nested finally blocks_

- [ ] 14. Run regression tests for all Python versions (3.9, 3.10, 3.11, 3.12)
  - [ ] 14.1 Test simple try/except/finally (no edge cases)
    - Verify existing functionality not broken
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
  
  - [ ] 14.2 Test nested try blocks with normal exception handling
    - Verify no regression in nested try/except
    - _Requirements: 3.2_
  
  - [ ] 14.3 Test try blocks with else clauses (non-3.1-specific)
    - Verify else clause handling unchanged
    - _Requirements: 3.3_
  
  - [ ] 14.4 Test shallow finally blocks (single level)
    - Verify basic finally handling unchanged
    - _Requirements: 3.4_
  - _Checkpoint: Verify no regressions in existing functionality_

- [ ] 15. Final checkpoint - Ensure all tests pass
  - [ ] 15.1 Run all test cases for bug fixes
    - D1, D2, D3, D4 bug fixes verified
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.4_
  
  - [ ] 15.2 Run regression tests
    - 3.9, 3.10, 3.11, 3.12 bytecode samples
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
  
  - [ ] 15.3 Verify decompiled code matches original source
    - Round-trip test: decompile -> recompile -> compare bytecode
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.8_
  
  - [ ] 15.4 Ask the user if questions arise
    - _Requirements: Implementation completion_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP (not applicable in this implementation)
- Each task references specific requirements from bugfix.md for traceability
- Checkpoints ensure incremental validation
- Version detection ensures Python 3.12-specific logic only applies to compatible versions
- Testing notes provide guidance for verifying each bug fix

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3", "2.4"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3", "3.4"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3", "4.4"] },
    { "id": 4, "tasks": ["5.1", "5.2", "5.3", "5.4", "5.5"] },
    { "id": 5, "tasks": ["6.1", "6.2", "6.3", "6.4"] },
    { "id": 6, "tasks": ["7.1", "7.2", "7.3"] },
    { "id": 7, "tasks": ["8.1", "8.2", "8.3", "8.4"] },
    { "id": 8, "tasks": ["9.1", "9.2", "9.3", "9.4"] },
    { "id": 9, "tasks": ["10.1", "10.2", "10.3", "11.1", "11.2", "11.3", "11.4"] },
    { "id": 10, "tasks": ["12.1", "12.2", "12.3", "12.4"] },
    { "id": 11, "tasks": ["13.1", "13.2", "13.3", "13.4"] },
    { "id": 12, "tasks": ["14.1", "14.2", "14.3", "14.4"] },
    { "id": 13, "tasks": ["15.1", "15.2", "15.3", "15.4"] }
  ]
}
```