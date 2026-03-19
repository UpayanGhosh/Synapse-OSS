# Review Feedback — Loop 1

Both reviewers returned **NEEDS CHANGES**. Address ALL items below before proceeding.

## Required Changes (Blocking)

### 1. Fix `ContextWindowTooSmallError` guard in `context_assembler.py` (Subtask 6)

**Problem:** The current guard formula `estimate_tokens(messages) + len(system_prompt)//4 > 16000` is inverted. It fires when content *exceeds* 16K tokens (i.e., on all healthy large conversations) instead of when the *remaining* context space is too small.

**Fix:** The correct check is:
```python
remaining = context_window_tokens - estimated_content_tokens
if remaining < CONTEXT_WINDOW_HARD_MIN_TOKENS:
    raise ContextWindowTooSmallError(...)
```

The `assemble_context()` signature already has `llm_model_id` — use it to resolve the actual model context window size (look up from a model registry dict keyed by model ID, or accept `context_window_tokens: int` as a direct parameter). Do NOT leave `llm_model_id` as a dangling parameter.

### 2. Add eviction/cleanup for `_STORE_LOCKS` and `_CACHE` in `session_store.py` (Subtask 2)

**Problem:** Both module-level dicts grow unbounded for the process lifetime. In a server running for days handling hundreds of unique session keys, this is a memory leak.

**Fix:** Follow the `SessionActorQueue` pattern at `workspace/sci_fi_dashboard/gateway/session_actor.py:47-51`:
- For `_STORE_LOCKS`: track a pending-count per key; delete the lock entry in `finally` when `pending_count` drops to 0.
- For `_CACHE`: cap at a maximum size (e.g. 200 entries) using an `OrderedDict` LRU eviction.

### 3. Add cross-process file locking to `session_store.py` (Subtask 2)

**Problem:** `asyncio.Lock` only protects within a single process. CLI + gateway writing `sessions.json` concurrently causes data corruption.

**Fix:** Use `filelock.FileLock` (already a project dependency — used in `sbs/profile/manager.py`) around the atomic write, in addition to the per-path `asyncio.Lock`. Replicate the pattern from `sbs/profile/manager.py _write_json()`.

## Architectural Strengths to Preserve

- Zero-modification to existing modules (additive-only approach)
- Parallel-layer design under `multiuser/` package
- Identity linker as pure function
- Compaction timeout handling (900s)
- Pattern replication from `PairingStore`, `SessionActorQueue`, `FileLock`
