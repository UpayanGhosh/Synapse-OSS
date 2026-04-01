# Agent Runtime & Inference Loop — Missing Features in Synapse-OSS

## Overview

openclaw's agent runtime (`src/agents/pi-embedded-runner/`) is a production-grade,
multi-attempt inference engine with typed retry state, auth-profile rotation, model
failover, overflow compaction, and a tool-loop circuit-breaker. Synapse-OSS uses a
simpler `SynapseLLMRouter` backed by `litellm.Router` and has none of the
structured attempt/retry machinery described here.

---

## 1. Multi-Attempt Inference Loop with Structured Retry State

### What openclaw has

**File:** `src/agents/pi-embedded-runner/run.ts`

`runEmbeddedPiAgent()` drives an outer `while` loop capped by
`resolveMaxRunRetryIterations()`. Each iteration is a full "attempt" that can
produce one of several failover outcomes:

- `auth` / `auth_permanent` — advance to the next auth profile
- `rate_limit` / `overloaded` — apply backoff then rotate profile
- `context_overflow` — trigger compaction and re-run
- `model_not_found` / `format` — raise immediately (non-retryable)
- `session_expired` — refresh runtime auth token and retry

The max iteration count scales with the number of configured auth profiles:

```ts
// src/agents/pi-embedded-runner/run/helpers.ts
const BASE_RUN_RETRY_ITERATIONS = 24;
const RUN_RETRY_ITERATIONS_PER_PROFILE = 8;
const MIN_RUN_RETRY_ITERATIONS = 32;
const MAX_RUN_RETRY_ITERATIONS = 160;

export function resolveMaxRunRetryIterations(profileCandidateCount: number): number {
  const scaled =
    BASE_RUN_RETRY_ITERATIONS +
    Math.max(1, profileCandidateCount) * RUN_RETRY_ITERATIONS_PER_PROFILE;
  return Math.min(MAX_RUN_RETRY_ITERATIONS, Math.max(MIN_RUN_RETRY_ITERATIONS, scaled));
}
```

Each attempt is dispatched to `runEmbeddedAttempt()` in
`src/agents/pi-embedded-runner/run/attempt.ts`, which wraps the pi-agent stream
and catches all exception classes to classify them.

### What Synapse-OSS has

`SynapseLLMRouter._do_call()` in `workspace/sci_fi_dashboard/llm_router.py` has a
single `try/except` block with no outer retry loop. The only retry is a one-shot
Copilot token refresh:

```python
except Exception as exc:
    if self._uses_copilot and "forbidden" in str(exc).lower():
        _get_copilot_token()
        self._rebuild_router()
        return await self._router.acompletion(...)
    raise
```

`execute_with_api_key_rotation()` iterates over a flat key list but has no concept
of attempts, compaction triggers, or structured retry state.

### Gap summary

Synapse-OSS has no multi-attempt inference loop. A single failure terminates the
request. There is no mechanism to: retry on overload after backoff, detect context
overflow and compact, or chain multiple recovery strategies in one run.

### Implementation notes for porting

1. Introduce an attempt counter and a `FailoverReason` enum mirroring
   `AuthProfileFailureReason` in `llm_router.py`.
2. Wrap `SynapseLLMRouter._do_call()` in an outer `for attempt in range(max_iterations)`
   loop similar to `resolveMaxRunRetryIterations()`.
3. Classify exceptions (`RateLimitError`, `AuthenticationError`, `BadRequestError`,
   `ServiceUnavailableError`) into retry buckets before deciding whether to rotate
   the key, sleep, or raise.
4. Thread an `AbortSignal`-equivalent (`asyncio.Event`) through to allow external
   cancellation of the loop.

---

## 2. Auth Profile Store with Cooldown, Failure-Count Backoff, and Model-Scoped Cooldowns

### What openclaw has

**Files:**
- `src/agents/auth-profiles/usage.ts` — `markAuthProfileFailure`, `markAuthProfileUsed`,
  `calculateAuthProfileCooldownMs`, `clearExpiredCooldowns`, `getSoonestCooldownExpiry`
- `src/agents/auth-profiles/types.ts` — `ProfileUsageStats`, `AuthProfileStore`

Each auth profile accumulates `errorCount`, `failureCounts` (per reason),
`cooldownUntil`, `disabledUntil`, and `cooldownModel`. The backoff schedule:

```ts
export function calculateAuthProfileCooldownMs(errorCount: number): number {
  if (errorCount <= 1) return 30_000;      // 30 s
  if (errorCount <= 2) return 60_000;      // 1 min
  return 5 * 60_000;                       // 5 min (max)
}
```

Billing / permanent-auth failures use an exponential `disabledUntil` up to 24 h,
configurable per-provider via `auth.cooldowns.billingBackoffHoursByProvider`.

Model-scoped cooldowns allow a rate-limited profile to still be used for a
_different_ model:

```ts
function shouldBypassModelScopedCooldown(stats, now, forModel?): boolean {
  return !!(
    forModel &&
    stats.cooldownReason === "rate_limit" &&
    stats.cooldownModel &&
    stats.cooldownModel !== forModel &&
    !isActiveUnusableWindow(stats.disabledUntil, now)
  );
}
```

Profile-failure state is persisted to disk with an
`updateAuthProfileStoreWithLock` call on every write.

### What Synapse-OSS has

`execute_with_api_key_rotation()` in `llm_router.py` tracks no per-key state.
It tries keys in order and stops at the first success or non-retryable error.
There is no concept of cooldown windows, error counters, or per-key backoff
between requests.

### Gap summary

Synapse-OSS provides round-robin key rotation but cannot detect that key A is
temporarily exhausted and park it for 30 s before retrying, while key B handles
requests in the meantime. Repeated failures on a billing-exhausted key will hammer
it on every request.

### Implementation notes for porting

1. Introduce a `ProfileUsageStore` dataclass mirroring `ProfileUsageStats`:
   `error_count`, `cooldown_until`, `disabled_until`, `failure_counts`, `cooldown_model`.
2. After each `execute_with_api_key_rotation` failure, call a `mark_failure(key, reason)`
   function that increments `error_count` and sets `cooldown_until`.
3. Before picking the next key, skip keys where `time.monotonic() < cooldown_until`.
4. Persist the store to disk using `atomicwrites` or `tempfile.mkstemp + os.replace`
   so state survives process restarts.
5. Clear expired cooldowns at the start of each rotation pass (mirrors
   `clearExpiredCooldowns` in openclaw).

---

## 3. Runtime Auth Refresh (Token Proactive Renewal)

### What openclaw has

**File:** `src/agents/pi-embedded-runner/run/auth-controller.ts`

`createEmbeddedRunAuthController()` creates a `runtimeAuthState` that includes a
background `setTimeout` to refresh short-lived tokens (e.g., GitHub Copilot tokens,
Vertex service-account tokens) _before_ they expire, without interrupting the
active inference stream:

```ts
// helpers.ts
export const RUNTIME_AUTH_REFRESH_MARGIN_MS = 5 * 60 * 1000;   // refresh 5 min early
export const RUNTIME_AUTH_REFRESH_RETRY_MS   = 60 * 1000;       // retry interval on failure
export const RUNTIME_AUTH_REFRESH_MIN_DELAY_MS = 5 * 1000;      // minimum delay between refreshes
```

The refresh fires in the background; if it fails, it retries on a 60 s interval.
The running LLM stream continues uninterrupted. On `session_expired` failover, the
controller calls `maybeRefreshRuntimeAuthForAuthError()` immediately.

**File:** `src/agents/runtime-auth-refresh.ts` — `clampRuntimeAuthRefreshDelayMs()`
ensures the proactive refresh never fires too soon or too late relative to
`expiresAt`.

### What Synapse-OSS has

`_get_copilot_token()` in `llm_router.py` is called reactively only after a
`"forbidden"` error occurs:

```python
if self._uses_copilot and "forbidden" in str(exc).lower():
    _get_copilot_token()
    self._rebuild_router()
```

There is no proactive background refresh; the token is always fetched after it
has already caused a failure.

### Gap summary

Synapse-OSS cannot proactively renew expiring tokens. Every token expiry causes at
least one failed LLM call before recovery. For long inference streams this leads to
mid-stream interruption and retry latency.

### Implementation notes for porting

1. Track `expires_at` for each OAuth / service-account token.
2. Schedule an `asyncio.create_task` that sleeps until `expires_at - MARGIN` and
   then refreshes the token, storing the new value in the profile store.
3. If the refresh fails, reschedule at `RETRY_MS` intervals.
4. On `AuthenticationError`, cancel any in-flight refresh and trigger an immediate
   one before retrying the LLM call.

---

## 4. Overflow-Triggered Compaction Inside the Inference Loop

### What openclaw has

**Files:**
- `src/agents/pi-embedded-runner/run/run.ts` — overflow detection in the main loop
- `src/agents/pi-embedded-runner/compact.ts` — `compactEmbeddedPiSession()`
- `src/agents/compaction.ts` — `summarizeInStages`, `pruneHistoryForContextShare`,
  `chunkMessagesByMaxTokens`, `summarizeWithFallback`
- `src/agents/pi-embedded-runner/run/compaction-timeout.ts` — per-attempt compaction
  timeout enforcement

When the inference attempt classifies the failure as `context_overflow`, the run
loop calls `compactEmbeddedPiSession()` before the next attempt. The compaction
pipeline:

1. Estimates tokens using a safety-margined heuristic (`SAFETY_MARGIN = 1.2`).
2. Splits history into equal-token chunks with `splitMessagesByTokenShare()`.
3. Summarizes each chunk independently, then merges summaries.
4. Falls back to partial summarization if oversized messages exist.
5. Repairs orphaned `tool_use` / `tool_result` pairs after dropping old chunks.
6. Rewrites the session transcript file atomically.

There is also a **compaction safety timeout** (`src/agents/pi-embedded-runner/run/compaction-retry-aggregate-timeout.ts`)
that limits the total wall-clock time spent in all compaction retries within one run,
so a hung summarization call cannot block the gateway indefinitely.

### What Synapse-OSS has

`compact_session()` in `workspace/sci_fi_dashboard/multiuser/compaction.py` exists
and is reasonably capable. It:
- Estimates tokens (chars ÷ 4).
- Splits into two halves and summarizes each.
- Merges summaries.
- Atomically rewrites the JSONL transcript.
- Has a 900 s timeout wrapper.

However, it is **never called from inside the LLM inference loop**. It is a
standalone utility. Nothing in `llm_router.py`, `session_actor.py`, or `main.py`
detects a context-overflow error from the LLM API and triggers compaction before
retrying.

### Gap summary

Synapse-OSS cannot self-heal from context-window overflow. A `BadRequestError`
due to a full context window terminates the request. The compaction utility exists
but is decoupled from the inference path.

### Implementation notes for porting

1. Detect `BadRequestError` with a token-count message from litellm (or check
   `response.usage.prompt_tokens >= context_window`).
2. On detection, call `compact_session()` passing the active `transcript_path`,
   `context_window_tokens`, and the current `llm_client`.
3. After compaction completes, reload the transcript and retry the LLM call.
4. Limit total compaction retries with an aggregate timeout (mirror
   `compaction-retry-aggregate-timeout.ts`).
5. Add a `summarizeWithFallback` equivalent: if full summarization fails (e.g.,
   the first half itself exceeds the context window), fall back to summarizing
   only small messages and inserting placeholder notes for oversized ones.

---

## 5. Tool-Loop Detection Circuit-Breaker

### What openclaw has

**File:** `src/agents/tool-loop-detection.ts`

Four configurable detectors with warning/critical/circuit-breaker thresholds:

| Detector | Description |
|---|---|
| `generic_repeat` | Hash-based detection of repeated identical tool calls |
| `known_poll_no_progress` | Detects polling tools (bash sleep, file watch) making no progress |
| `ping_pong` | Detects alternating pairs of tool calls |
| `global_circuit_breaker` | Fires when total distinct tool calls exceed 30 |

Thresholds (configurable via `ToolLoopDetectionConfig`):

```ts
export const WARNING_THRESHOLD           = 10;
export const CRITICAL_THRESHOLD          = 20;
export const GLOBAL_CIRCUIT_BREAKER_THRESHOLD = 30;
```

At `warning` level, a diagnostic message is injected. At `critical`, the agent
aborts with a `ToolLoopError` which is reported to the requester.

### What Synapse-OSS has

No equivalent. There is no tool-call history tracking and no circuit-breaker that
would interrupt an agent stuck in a polling loop.

### Gap summary

Without tool-loop detection, a Synapse-OSS agent can run indefinitely (or until
the context window fills) if the model repeatedly calls the same tool. This wastes
API tokens and can block the session queue.

### Implementation notes for porting

1. Maintain a sliding window of the last N tool-call signatures (role + name + args hash).
2. After each tool call, check the window for `generic_repeat` and `ping_pong` patterns.
3. On `warning`, prepend an injection message to the next LLM turn.
4. On `critical`, raise a `ToolLoopError` and close the session.
5. Wire the detection into `SynapseLLMRouter` or into the gateway worker
   (`workspace/sci_fi_dashboard/gateway/worker.py`) between tool execution and
   the next LLM call.
