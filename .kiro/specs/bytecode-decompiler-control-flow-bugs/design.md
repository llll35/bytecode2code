# Design Document: Control Flow Reconstruction Bug Fixes

## Introduction

This document describes the architectural changes needed to fix four control flow reconstruction bugs in the Python bytecode decompiler's exception handling (`try`/`except`/`finally`/`else`) support across Python versions 3.9, 3.10, 3.11, and 3.12.

The bugs cause incorrect decompilation where code after `try`-`except` blocks is incorrectly swallowed, collapsed, or improperly handled, leading to loss of definitions and statements.

## Root Cause Analysis

### Current Implementation Issues

The decompiler in `bytecode2code/decompiler.py` has several methods for parsing exception handlers:
- `_parse_except_handlers`: Parses the full handler chain
- `_parse_handler_body`: Emits one except handler's body  
- `_recover_else_clause`: Recovers an `else` clause between body and handler
- `_collect_finally_body`: Recovers the `finally` clause body
- `_continue_over_handler`: Recovers `continue` statements after try/finally
- `_consume_back_edge`: Skips implicit loop back edges after try/finally

However, the implementation has several gaps:

1. **Missing handler exit redirection**: Methods `_redirect_handler_exits` and `_save_tail_for_merge` are referenced in the bugfix requirements but not implemented in `decompiler.py`. These methods exist in the version-specific `pyvers/decomp311.py` but are needed in the base decompiler.

2. **Incomplete Python 3.12 support**: Python 3.12 changed how module-level try/except blocks compile: the tail code (code after the try/except) is placed *before* the handler (at `entry.end`) rather than after, and the handler jumps backward to it. The current decompiler doesn't handle this retargeting.

3. **Break/continue restoration**: When `break` or `continue` appear in try bodies, the compiler generates backward jumps that the decompiler misinterprets as loop back edges instead of loop control statements.

4. **Nested finally collapsing**: Python 3.11/3.12 emit nested finally blocks differently, and the current `_collect_finally_body` method doesn't properly handle deeply nested finally structures.

## Architecture Changes

### Core Algorithm: Exception Handling Control Flow Reconstruction

The decompiler processes exception handling using a stack-based approach:

```
1. When SETUP_FINALLY/SETUP_EXCEPT is encountered:
   - Push BlockInfo onto _exc_stack with except_target, instr_start, try_end_idx
   - Scan forward to find POP_BLOCK that closes the try body

2. When POP_BLOCK is encountered for an exception block:
   - Pop the block info from _exc_stack
   - Parse exception handlers starting at except_target
   - For try/finally (no except handlers): collect finally body inline
   - For try/except: parse handler chain and recover else clause

3. Handler exit redirection (NEW):
   - For handlers with backward jumps, redirect to merge point
   - Save tail instructions to be emitted at merge point

4. Loop exit recovery:
   - Detect and emit break/continue statements at loop boundaries
   - Skip implicit back edges that follow try/finally blocks
```

### Method Specifications

#### New Methods

##### `_redirect_handler_exits(self, instructions: List[Instruction])`

**Purpose**: Retarget handler exit jumps from backward to forward, and save tail instructions for later emission.

**Root Cause**: Python 3.12 module-level code places the tail (code after try/except) *before* the handler and lets handlers jump backward to it. The stock decompiler misinterprets this as a loop back edge.

**Algorithm**:
```python
def _redirect_handler_exits(self, instructions: List[Instruction]) -> None:
    """Retarget handler exit jumps and save tail instructions for Python 3.12+.
    
    For each exception entry:
    - Find the RERAISE that ends the handler
    - For each backward jump (target < handler_start) in the handler:
      - If jump target equals entry.end (Python 3.12 tail placement):
        * Retarget to merge point (past all handlers)
        * Save tail instructions (entry.end to handler_start) for emission at merge
      - Otherwise:
        * Retarget to merge point directly
    """
    # Implementation details:
    # 1. Iterate through exception entries from co_exceptiontable
    # 2. For each entry, find handler start (entry.target) and RERAISE
    # 3. For each jump instruction before RERAISE:
    #    - If backward jump to entry.end: retarget to merge + save tail
    #    - If backward jump elsewhere: retarget to merge
    # 4. Store saved tails in _tails_at_merge dict keyed by merge offset
    ```
    
**Interaction with other methods**:
- Called by `run()` after `_parse_except_handlers` returns
- Populates `_tails_at_merge` which `run()` uses to emit saved instructions

##### `_save_tail_for_merge(self, instructions: List[Instruction], tail_start: int, merge_offset: int)`

**Purpose**: Collect instructions from the tail region (after try/except) that should be emitted at the merge point instead of at their original location.

**Root Cause**: In Python 3.12, the compiler duplicates the tail code before the handler and lets handlers jump back to it. The decompiler must emit this code only once, at the merge point.

**Algorithm**:
```python
def _save_tail_for_merge(self, instructions: List[Instruction], tail_start: int, merge_offset: int) -> None:
    """Save tail instructions to emit at the merge point.
    
    Collects instructions from tail_start (inclusive) to handler_start (exclusive)
    and stores them in _tails_at_merge[merge_offset].
    
    Also marks original tail instructions as _drops so they're not emitted twice.
    """
    # 1. Find handler_start (first instruction after tail_start that's part of handler)
    # 2. Collect all instructions with offset in [tail_start, handler_start)
    # 3. Store in _tails_at_merge[merge_offset] = collected_instructions
    # 4. Add each collected instruction's offset to _drops set
```

**Interaction with other methods**:
- Called by `_redirect_handler_exits` when detecting Python 3.12 tail placement
- Read by `run()` method to emit saved instructions at merge points

##### `_merge_offset(self, instructions: List[Instruction], handler_start_idx: int, target_offset: int) -> int`

**Purpose**: Calculate the offset just past all handlers belonging to a try block.

**Algorithm**:
```python
def _merge_offset(self, instructions: List[Instruction], handler_start_idx: int, target_offset: int) -> int:
    """Calculate merge point offset after all handlers."""
    # 1. Find all exception entries that belong to the same try block
    # 2. Find the handler entry with the largest end offset
    # 3. Return index of first instruction after that handler's end
```

##### `_restore_break_continue(self, instructions: List[Instruction], pop_idx: int, handler_start_idx: int, target_offset: int, try_end_idx: int)`

**Purpose**: Detect and restore `break` and `continue` statements that the compiler emits after try blocks.

**Root Cause**: When `break` or `continue` appears in a try body, the compiler emits:
- The loop exit instruction (POP_BLOCK + JUMP for break, or just JUMP for continue)
- Then the handler chain
- Then the loop back edge (implicit after try/finally)

The decompiler needs to detect these jumps and convert them to AST nodes.

**Algorithm**:
```python
def _restore_break_continue(self, instructions: List[Instruction], pop_idx: int, 
                            handler_start_idx: int, target_offset: int, try_end_idx: int) -> List[ast.stmt]:
    """Detect break/continue jumps at try block boundaries."""
    tail_jumps = []
    i = try_end_idx + 1
    
    # Check for break: POP_BLOCK + unconditional forward jump
    if i < len(instructions) and instructions[i].opname == "POP_BLOCK":
        i += 1
        if i < len(instructions) and instructions[i].opname in ("JUMP_FORWARD", "JUMP_ABSOLUTE"):
            jump_instr = instructions[i]
            target = int(jump_instr.argval or (jump_instr.arg or 0))
            
            # Forward jump (target > current offset) = break
            if target > jump_instr.offset:
                tail_jumps.append(ast.Break())
            # Backward jump = continue (handled separately by _continue_over_handler)
    
    return tail_jumps
```

#### Modified Methods

##### `_process_instruction` (POP_BLOCK handling)

**Current behavior**: Handles POP_BLOCK for exception blocks, parses handlers, and emits try/except/finally.

**Required changes**:
1. After parsing handlers, call `_redirect_handler_exits` if needed
2. For handlers with backward jumps, apply retargeting before continuing
3. Handle saved tail emission via `_tails_at_merge`

**Pseudocode**:
```python
if opname == "POP_BLOCK" and self._exc_stack:
    block = self._exc_stack.pop()
    
    # ... existing handler parsing code ...
    
    # NEW: Apply handler exit redirection
    if self._needs_redirect(instructions, handler_start_idx, target):
        self._redirect_handler_exits(instructions)
    
    # ... rest of existing code ...
```

##### `_emit_statements` (loop exit handling)

**Current behavior**: Scans for while conditions, while True loops, and other control flow.

**Required changes**:
1. Check for saved tail instructions at current position
2. Emit saved tail before continuing normal statement emission

**Pseudocode**:
```python
def _emit_statements(self, code, instructions, ...):
    i = start
    while i < n:
        # NEW: Emit saved tail instructions at this offset
        if hasattr(self, '_tails_at_merge') and i < len(instructions):
            offset = instructions[i].offset
            if offset in self._tails_at_merge:
                for tail_instr in self._tails_at_merge[offset]:
                    # Convert 3.12 instructions to 3.9 form and emit
                    converted = self._convert_312_to_39_instruction(tail_instr)
                    self._emit_single_statement(converted, ...)
        
        # ... rest of existing statement emission code ...
```

##### `_parse_except_handlers`

**Current behavior**: Parses the handler chain and recovers else clause.

**Required changes**: None - this method already handles handler chain parsing correctly.

##### `_collect_finally_body`

**Current behavior**: Recovers finally clause for try/finally blocks.

**Required changes**: Handle deeply nested finally blocks by detecting when a finally handler contains another SETUP_FINALLY.

**Algorithm**:
```python
def _collect_finally_body(self, code, instructions, try_end_idx, handler_start_idx):
    # ... existing collection logic ...
    
    # NEW: Handle nested finally blocks
    nested_finally = False
    for i in range(handler_start_idx, len(instructions)):
        if instructions[i].opname == "SETUP_FINALLY":
            # Found nested finally - need to collect it separately
            nested_finally = True
            break
    
    if nested_finally:
        # Collect outer finally up to nested SETUP_FINALLY
        # Then recursively process nested finally
        pass
    
    return body, resume
```

### Python Version Differences

| Feature | Python 3.9 | Python 3.10 | Python 3.11 | Python 3.12 |
|---------|-----------|-------------|-------------|-------------|
| Tail placement | After handlers | After handlers | After handlers | **Before handlers** (entry.end) |
| Handler exit jumps | Forward over handlers | Forward over handlers | Forward over handlers | **Backward to tail** |
| Nested finally layout | Inline copy, then handler copy | Inline copy, then handler copy | **Inline + tail mixed** | **Inline + tail mixed** |
| Loop exit jumps | POP_BLOCK + forward jump | POP_BLOCK + forward jump | POP_BLOCK + forward jump | POP_BLOCK + forward jump |

### Data Structures

#### New Instance Variables

```python
class Decompiler:
    def __init__(self):
        # ... existing initialization ...
        
        # NEW: Store saved tail instructions keyed by merge offset
        self._tails_at_merge: Dict[int, List[Instruction]] = {}
        
        # NEW: Track retargeted jumps
        self._retarget: Dict[int, int] = {}  # original_offset -> new_target
        
        # NEW: Track dropped instructions to avoid double-emission
        self._drops: Set[int] = set()
```

## Algorithm Design

### Complete Exception Handling Flow

```
1. Encounter SETUP_FINALLY/SETUP_EXCEPT
   ↓
2. Push BlockInfo onto _exc_stack
   ↓
3. Scan forward to find POP_BLOCK (try_end_idx)
   ↓
4. Parse exception handlers starting at except_target
   ↓
5. If handler chain found (try/except):
   a. Parse each handler body
   b. Recover else clause
   c. Set skip_to = post_handler_idx
   ↓
6. If no handler chain found (try/finally):
   a. Collect finally body inline (from try_end_idx+1 to handler_start)
   b. Set skip_to = resume or post_handler_idx
   ↓
7. Emit try/except/finally AST node with collected bodies
   ↓
8. NEW: Apply handler exit redirection
   a. For each handler with backward jumps:
      - If backward jump to entry.end: retarget to merge + save tail
      - Otherwise: retarget to merge
   b. Call _redirect_handler_exits()
   ↓
9. Continue emitting statements from skip_to position
   ↓
10. NEW: At merge point, emit saved tail instructions
    a. Check if current offset in _tails_at_merge
    b. Emit each saved instruction (converted from 3.12 to 3.9 form)
```

### Break/Continue Detection Flow

```
1. After try block ends (at try_end_idx + 1):
   ↓
2. Check if next instruction is POP_BLOCK
   ↓
3. If POP_BLOCK, check next for JUMP_FORWARD/JUMP_ABSOLUTE
   ↓
4. Determine jump type:
   - Forward jump (target > offset) = break
   - Backward jump (target ≤ offset) = continue
   ↓
5. Emit appropriate AST node (ast.Break or ast.Continue)
   ↓
6. Continue from jump target (or handler start for continue)
```

### Nested Finally Handling

```
1. Collect finally body from try_end_idx+1
   ↓
2. Scan collected body for SETUP_FINALLY
   ↓
3. If found:
   a. Split collection at SETUP_FINALLY
   b. Collect inner finally recursively
   c. Combine outer and inner finally bodies
   ↓
4. Return combined body and resume index
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Exception Handler Exit Redirection

*For any* exception handler in a try/except block, if the handler contains a backward jump, the decompiler shall redirect that jump to the merge point (the instruction after all handlers) rather than leaving it as a backward jump.

**Validates: Requirements 1.1, 1.2**

### Property 2: Tail Instruction Emission at Merge Point

*For any* Python 3.12 module-level try/except block where the tail code is placed before the handler, the decompiler shall save the tail instructions and emit them at the merge point rather than at their original location.

**Validates: Requirements 1.1**

### Property 3: Break Statement Recovery

*For any* try/except block that ends with a `break` statement, the decompiler shall emit an `ast.Break` node immediately following the try/except node, and the loop containing the try block shall have the correct exit boundary.

**Validates: Requirements 1.2, 2.2**

### Property 4: Continue Statement Recovery

*For any* try/finally block that ends with a `continue` statement, the decompiler shall emit an `ast.Continue` node at the appropriate position, and the loop containing the try/finally shall have the correct exit boundary.

**Validates: Requirements 1.2, 2.2**

### Property 5: Else Clause Preservation

*For any* try/except block with an else clause, the decompiler shall correctly identify the else clause boundaries and include it in the `orelse` field of the try/except AST node.

**Validates: Requirements 1.3, 3.3**

### Property 6: Nested Finally Structure Preservation

*For any* deeply nested finally blocks, the decompiler shall preserve the hierarchical structure in the AST, with each finally body correctly associated with its corresponding try/except block.

**Validates: Requirements 1.4, 2.4**

### Property 7: Control Flow Integrity

*For any* try/except/finally construct, the decompiled code shall have the same control flow as the original bytecode, with no statements swallowed or duplicated.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4**

### Property 8: Version-Independent Semantics

*For any* try/except construct across Python versions 3.9, 3.10, 3.11, and 3.12, the decompiler shall produce semantically equivalent output despite differences in how each version compiles exception handling.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.2**

## Implementation Checklist

- [ ] Implement `_redirect_handler_exits(instructions)` method
- [ ] Implement `_save_tail_for_merge(instructions, tail_start, merge_offset)` method
- [ ] Implement `_merge_offset(instructions, handler_start_idx, target_offset)` helper
- [ ] Implement `_restore_break_continue(instructions, pop_idx, handler_start_idx, target_offset, try_end_idx)` method
- [ ] Add `_tails_at_merge`, `_retarget`, `_drops` to `__init__`
- [ ] Modify `_process_instruction` POP_BLOCK handler to call redirection methods
- [ ] Modify `_emit_statements` to emit saved tail instructions at merge points
- [ ] Update `_collect_finally_body` to handle nested finally blocks
- [ ] Add version detection for Python 3.12-specific handling
- [ ] Test with Python 3.9, 3.10, 3.11, and 3.12 bytecode samples
- [ ] Verify no regression in existing functionality

## References

- `bytecode2code/pyvers/decomp311.py`: Existing implementation of handler exit redirection for Python 3.11/3.12
- `bugfix.md`: Bugfix requirements document detailing expected behavior
- CPython bytecode documentation for exception handling in Python 3.9-3.12
