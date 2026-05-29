# Session Management & Compaction — Missing Features in Synapse-OSS

## Overview

openclaw's session layer (`src/agents/session-write-lock.ts`,
`src/agents/pi-embedded-runner/session-manager-cache.ts`,
`src/agents/pi-embedded-runner/compact.ts`) provides:
- Cross-process file locking with PID-recycling detection and watchdog release.
- An LRU TTL cache in front of every session store read.
- Compaction integrated into the inference loop, including a safety timeout and
  multiple retry strategies.

Synapse-OSS's `SessionStore` in `workspace/sci_fi_dashboard/multiuser/session_store.py`
is well-designed but missing several production-hardening features present in openclaw.

---

## 1. Session Write Lock — Cross-Process with Stale-Lock Reclaim and Watchdog

### What openclaw has

**File:** `src/agents/session-write-lock.ts`

`acquireSessionWriteLock()` implements a full exclusive file lock:

- Creates a `.jsonl.lock` file containing `{pid, createdAt, starttime}` (where
  `starttime` is the PID's start time from `/proc/pid/stat` field 22).
- On contention, reads the lock file and checks:
  - Is the PID alive?
  - Has the PID been recycled (same PID, different `starttime`)?
  - Is the lock older than `staleMs` (default 30 min)?
  - Falls back to `mtime` staleness if the lock file has no parseable metadata.
- If stale, atomically removes the lock file and retries (`EEXIST` loop).
- Supports **reentrant** acquisition (same process, same file: reference-counted).
- Runs a **watchdog timer** every 60 s that force-releases locks held longer than
  `maxHoldMs` (default 5 min) to prevent deadlocks from crashed workers.
- Registers `SIGINT`, `SIGTERM`, `SIGQUIT`, `SIGABRT` handlers to release all
  held locks synchronously on process exit.
- `cleanStaleLockFiles()` scans a sessions directory and removes all stale lock
  files at startup, preventing cold-start deadlocks.

This is substantially more robust than a simple `filelock.FileLock`, particularly
the PID-recycling check and the watchdog:

```ts
const pidRecycled =
  pidAlive && pid !== null && storedStarttime !== null
    ? (() => {
        const currentStarttime = getProcessStartTime(pid);
        return currentStarttime !== null && currentStarttime !== storedStarttime;
      })()
    : false;
```

### What Synapse-OSS has

`SessionStore._update_sync()` in `session_store.py` uses `filelock.FileLock` with a
30 s timeout. This correctly prevents concurrent writes to the same store file.
However:
- No PID-recycling detection.
- No watchdog to release locks held by dead processes.
- No stale-lock cleanup on startup.
- `filelock` will raise `Timeout` after 30 s but does not inspect the holding
  process to determine if it is alive.

### Gap summary

In a multi-process deployment (e.g., Gunicorn with multiple workers), if one worker
dies while holding the `filelock`, the 30 s timeout will block all other workers
from writing to that session store. openclaw's implementation detects the dead PID
and reclaims the lock immediately.

### Implementation notes for porting

1. Write the holder's `pid` and `/proc/pid/stat` `starttime` to the lock file.
2. On contention, read the lock file and call `os.kill(pid, 0)` to check if the
   PID is alive.
3. If the PID is dead or the `starttime` has changed, delete the lock file and
   retry immediately.
4. Add a background thread or `asyncio.Task` to check all held locks every 60 s
   and force-release any held longer than `max_hold_seconds`.
5. At startup, scan the sessions directory for `.lock` files and delete any that
   are stale by the same PID-alive / age check.

---

## 2. Session Manager LRU Cache with TTL

### What openclaw has

**File:** `src/agents/pi-embedded-runner/session-manager-cache.ts`

`SessionManagerCache` wraps the pi-agent's `SessionManager` with a typed LRU
cache. Each entry carries a TTL; on access the TTL is extended (sliding expiry).
When the cache is full, the least-recently-used entry is evicted and its
`SessionManager` is disposed (flushing any pending state).

The cache size and TTL are tuned to the expected concurrency of the gateway. A
cache miss causes a disk read of the session transcript; a hit returns the in-memory
`SessionManager` directly, avoiding re-parsing the full JSONL file.

**File:** `src/agents/pi-embedded-runner/session-manager-init.ts`

`initSessionManager()` pre-warms the session manager for a session key, preparing
bootstrap context, compaction state, and history limits before the first inference
call. This amortizes the startup cost of long sessions across multiple sequential
messages.

### What Synapse-OSS has

`SessionStore` in `session_store.py` has a module-level `OrderedDict`-based LRU
cache (max 200 entries) with a TTL controlled by
`SYNAPSE_SESSION_CACHE_TTL_MS` (default 45 s).

This is a good start. The gap is that the cache only covers the session _metadata_
(`compaction_count`, `memory_flush_at`, etc.), not the full transcript / active
conversation state. Every message requires re-reading the `.jsonl` transcript from
disk.

### Gap summary

Synapse-OSS caches session metadata correctly but not the parsed conversation
history. For high-frequency sessions (e.g., rapid-fire Telegram messages), this
means repeated JSONL reads and JSON parsing on every turn.

### Implementation notes for porting

1. Introduce a `ConversationCache` that maps `session_key` → `list[dict]` (parsed
   messages) with a configurable TTL (e.g., 60 s after last access).
2. On cache hit, append the new turn to the in-memory list before the LLM call.
3. After compaction, invalidate the cache entry so the next read reloads from disk.
4. Cap cache size to prevent memory growth under high concurrency (max N sessions,
   e.g. 100, using `OrderedDict` eviction same as existing `_CACHE`).

---

## 3. Compaction — Adaptive Chunk Ratio and Oversized-Message Fallback

### What openclaw has

**File:** `src/agents/compaction.ts`

openclaw's compaction has several refinements absent from Synapse-OSS:

**Adaptive chunk ratio** (`computeAdaptiveChunkRatio`): When individual messages are
large relative to the context window, the chunk ratio is reduced so each chunk fits
within the summarization model's own context limit:

```ts
export const BASE_CHUNK_RATIO = 0.4;
export const MIN_CHUNK_RATIO = 0.15;
export const SAFETY_MARGIN = 1.2; // 20% buffer for token estimation inaccuracy

export function computeAdaptiveChunkRatio(messages, contextWindow): number {
  const avgTokens = totalTokens / messages.length;
  const safeAvgTokens = avgTokens * SAFETY_MARGIN;
  const avgRatio = safeAvgTokens / contextWindow;
  if (avgRatio > 0.1) {
    const reduction = Math.min(avgRatio * 2, BASE_CHUNK_RATIO - MIN_CHUNK_RATIO);
    return Math.max(MIN_CHUNK_RATIO, BASE_CHUNK_RATIO - reduction);
  }
  return BASE_CHUNK_RATIO;
}
```

**Oversized-message fallback** (`summarizeWithFallback`): If full summarization
fails (e.g., a single tool result exceeds 50% of the context window), openclaw
falls back to summarizing only the small messages and inserting placeholder notes
for oversized ones. If even that fails, it returns a minimal "context unavailable"
summary rather than raising.

**History pruning** (`pruneHistoryForContextShare`): Before summarization, oldest
message chunks are dropped until the remaining history fits within the configured
`maxHistoryShare` (default 50% of context). Orphaned `tool_use` / `tool_result`
pairs are repaired after each drop.

**Identifier preservation policy** (`AgentCompactionIdentifierPolicy`): The
summarization prompt can be configured with `strict` (always preserve UUIDs,
hashes, IPs), `off`, or `custom` instructions. This prevents summaries from
paraphrasing or truncating opaque identifiers that the agent will need later.

### What Synapse-OSS has

`compact_session()` in `multiuser/compaction.py`:
- Splits into exactly 2 halves and summarizes each.
- Has `strip_tool_result_details()` (drops `role == "tool"` messages).
- Has `_repair_orphaned_tool_pairs()`.
- Has a 900 s aggregate timeout.
- Has a memory-flush guard (writes a daily note before compacting).

Missing:
- No adaptive chunk ratio based on average message size.
- No oversized-message fallback path.
- No history pruning before summarization.
- No identifier preservation instructions.
- Fixed to exactly 2 halves; cannot summarize in 3+ chunks for very long histories.

### Gap summary

For sessions with very large individual messages (e.g., long bash outputs stored as
tool results), Synapse-OSS's compaction will fail because the summarization call
itself exceeds the model's context. There is no fallback.

### Implementation notes for porting

1. Port `compute_adaptive_chunk_ratio(messages, context_window)` that reduces the
   chunk size when average message tokens are large.
2. Add `summarize_with_fallback()` that catches `BadRequestError` from the
   summarization call and retries with oversized messages filtered out.
3. Add `prune_history_for_context_share(messages, max_context_tokens, max_share=0.5)`
   that drops the oldest chunk until the remaining messages fit within the budget.
4. Add identifier preservation instructions to the summarization system prompt
   (a single paragraph instructing the model to preserve UUIDs, hashes, etc.).
5. Parameterize the number of split parts (currently hardcoded to 2) so very long
   sessions can be summarized in 3–4 chunks.

---

## 4. Compaction Safety Timeout and Retry Aggregate Guard

### What openclaw has

**Files:**
- `src/agents/pi-embedded-runner/run/compaction-timeout.ts`
- `src/agents/pi-embedded-runner/run/compaction-retry-aggregate-timeout.ts`

Two layers of compaction timeout:

1. **Per-attempt timeout**: Each individual summarization call has a timeout. If
   it exceeds the limit, the attempt is aborted and the run falls back to history
   pruning without summarization.

2. **Aggregate timeout**: The total time spent across all compaction retries in a
   single `runEmbeddedPiAgent()` call is bounded. If the aggregate exceeds the
   limit, no further compaction attempts are made for this run; the agent continues
   with whatever history remains.

This prevents a model outage (slow summarization responses) from blocking a gateway
slot indefinitely.

### What Synapse-OSS has

`compact_session()` wraps `_compact_inner()` in a single `asyncio.wait_for(..., timeout=900)`.
This is a 15-minute aggregate timeout for the entire compaction cycle.

There is no per-summarization-call timeout and no aggregate guard for multiple
compaction retries within one run.

### Gap summary

If a summarization call hangs at the provider level (e.g., no response for 5 min),
Synapse-OSS will block the session actor for up to 15 minutes. During this time the
session queue backs up for all other messages from the same user.

### Implementation notes for porting

1. Add a per-call timeout (e.g., 120 s) to each `llm_client.acompletion()` call
   inside `_compact_inner()`.
2. Track the total compaction time across the current run; once it exceeds a
   configurable limit (e.g., 5 min), skip further compaction and continue with
   pruning only.
3. Expose these limits as config keys: `compaction_per_call_timeout_s` and
   `compaction_aggregate_timeout_s`.

---

## 5. Session Transcript Repair — Tool-Use / Tool-Result Pairing

### What openclaw has

**File:** `src/agents/session-transcript-repair.ts`

`repairToolUseResultPairing()` is called at multiple points:
- After dropping an old chunk during history pruning.
- After atomic transcript rewrite during compaction.
- During session file repair at startup (`session-file-repair.ts`).

It removes any `tool_result` (role=`tool`) message whose `tool_call_id` does not
match an existing `tool_use` in the remaining messages, and vice versa. This
prevents "unexpected tool_use_id" API errors from Anthropic and similar providers.

The repair is tracked: `repairReport.droppedOrphanCount` is added to the
`droppedMessages` count so token budget calculations remain accurate.

### What Synapse-OSS has

`_repair_orphaned_tool_pairs()` in `compaction.py` does the same thing but only
during compaction. It is not called:
- After history pruning (which doesn't exist yet).
- At session startup.
- When the transcript file is partially written (crash recovery).

### Gap summary

If a session transcript is corrupted (e.g., a tool_use was written but the process
crashed before the tool_result was appended), the session will fail on the next LLM
call with a provider error. openclaw repairs this at startup; Synapse-OSS does not.

### Implementation notes for porting

1. Call `_repair_orphaned_tool_pairs()` at transcript load time, not just during
   compaction.
2. Add a startup scan that repairs all session transcripts in the sessions directory
   (mirroring `src/agents/session-file-repair.ts`).
3. Return a repair report (count of dropped pairs) from the repair function so
   callers can log the event without masking it silently.
