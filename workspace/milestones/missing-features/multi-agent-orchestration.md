# Multi-Agent Orchestration — Missing Features in Synapse-OSS

## Overview

openclaw has a full multi-agent spawning and registry system under
`src/agents/subagent-*.ts`. This covers subagent lifecycle (spawn, steer, announce
completion, orphan recovery), depth-limiting, the ACP (Agent Coordination Protocol)
binding layer, and persistent run records. Synapse-OSS has no equivalent; a single
session actor handles all work sequentially.

---

## 1. Subagent Registry — Lifecycle, Persistence, and Orphan Recovery

### What openclaw has

**Core files:**
- `src/agents/subagent-registry.ts` — entry point; listener bootstrap, sweeper loop
- `src/agents/subagent-registry-state.ts` — `persistSubagentRunsToDisk`, `restoreSubagentRunsFromDisk`, `getSubagentRunsSnapshotForRead`
- `src/agents/subagent-registry-memory.ts` — in-memory `subagentRuns: Map<string, SubagentRunRecord>`
- `src/agents/subagent-registry-lifecycle.ts` — `createSubagentRegistryLifecycleController`
- `src/agents/subagent-registry-completion.ts` — `emitSubagentEndedHookOnce`
- `src/agents/subagent-orphan-recovery.ts` — detects runs that restarted across process crashes

The registry maintains a `Map<runId, SubagentRunRecord>` in memory and writes it to
disk on every state transition. On gateway restart, `restoreSubagentRunsFromDisk()`
merges persisted records so runs that were active before the crash are visible to
the new process. Cross-process visibility is achieved through
`getSubagentRunsSnapshotForRead()`, which merges disk state with in-memory state on
every read.

The sweeper loop runs periodically to:
- Finalize stale runs (announce timeout = 120 s, lifecycle-error retry grace = 15 s).
- Trigger `reconcileOrphanedRun()` for runs restored from disk that were neither
  completed nor killed before the process exited.

Relevant constants:
```ts
const SUBAGENT_ANNOUNCE_TIMEOUT_MS = 120_000;
const LIFECYCLE_ERROR_RETRY_GRACE_MS = 15_000;
```

`SubagentRunRecord` fields include `runId`, `sessionKey`, `childSessionKey`,
`requesterOrigin`, `startedAt`, `endedAt`, `endedReason`, `outcome`, and
`attachmentsDir`.

### What Synapse-OSS has

`SessionActorQueue` in `workspace/sci_fi_dashboard/gateway/session_actor.py` is a
per-key FIFO that serializes operations on the same session key. It has no concept
of subagents, no run records, and no persistence. If the process restarts, all
in-flight session state is lost.

### Gap summary

Synapse-OSS cannot spawn or track child agents. All processing is single-threaded
per session key with no awareness of parent–child relationships or orphan recovery.

### Implementation notes for porting

1. Define a `SubagentRecord` dataclass with `run_id`, `session_key`,
   `child_session_key`, `started_at`, `ended_at`, `outcome`.
2. Persist records to a JSON file on each state transition (atomic write).
3. On startup, load persisted records and reconcile with the current process:
   mark as orphaned any run whose `ended_at` is null.
4. Add a sweeper `asyncio.Task` to finalize timed-out announce flows.

---

## 2. Subagent Spawn — Depth Limiting and Workspace Isolation

### What openclaw has

**Files:**
- `src/agents/subagent-spawn.ts` — `spawnSubagent()`
- `src/agents/subagent-depth.ts` — `getSubagentDepthFromSessionStore()`
- Config: `DEFAULT_SUBAGENT_MAX_SPAWN_DEPTH` from `src/config/agent-limits.ts`

When spawning a subagent, openclaw:
1. Reads the parent's `spawnDepth` from the session store.
2. Rejects the spawn if `childDepth >= maxSpawnDepth`.
3. Assigns the child an isolated workspace directory (or inherits the parent's).
4. Writes the `spawnedBy` relationship to the session store so depth can be
   reconstructed from disk after a restart.

`getSubagentDepthFromSessionStore()` walks the `spawnedBy` chain recursively to
derive depth even when the explicit `spawnDepth` field is missing:

```ts
const depthFromStore = (key: string): number | undefined => {
  ...
  const spawnedBy = normalizeSessionKey(entry?.spawnedBy);
  if (spawnedBy) {
    const parentDepth = depthFromStore(spawnedBy);
    return parentDepth !== undefined ? parentDepth + 1 : getSubagentDepth(spawnedBy) + 1;
  }
  return undefined;
};
```

### What Synapse-OSS has

There is no spawn mechanism. The MCP server (`workspace/sci_fi_dashboard/mcp_servers/synapse_server.py`)
exposes tools but does not spawn sub-sessions. There is no depth tracking.

### Gap summary

Synapse-OSS has no way to run nested agents, limit recursion depth, or isolate
child workspaces from the parent.

### Implementation notes for porting

1. Store `spawned_by` and `spawn_depth` in the session metadata when creating a
   child session.
2. Before spawning, read the parent's depth from the store and reject if
   `child_depth >= config.max_spawn_depth`.
3. Provide `get_subagent_depth_from_store(session_key)` that walks the `spawned_by`
   chain recursively, mirroring `getSubagentDepthFromSessionStore`.

---

## 3. Subagent Announce Flow — Completion Routing Back to Parent

### What openclaw has

**Files:**
- `src/agents/subagent-announce.ts` — `runSubagentAnnounceFlow`, `buildSubagentSystemPrompt`
- `src/agents/subagent-announce-delivery.ts` — `runAnnounceDeliveryWithRetry`,
  `deliverSubagentAnnouncement`
- `src/agents/subagent-announce-queue.ts` — per-session announcement queue with
  idempotency
- `src/agents/subagent-announce-output.ts` — `readSubagentOutput`, `waitForSubagentRunOutcome`
- `src/agents/announce-idempotency.ts` — `buildAnnounceIdempotencyKey`

When a subagent finishes, openclaw runs an "announce flow":
1. Reads the child's output (last message / tool result).
2. Builds a compact stats line summarizing tokens used and duration.
3. Delivers a structured announcement message to the parent session via the gateway.
4. Retries delivery with exponential backoff if the parent's session is not yet
   ready to receive.
5. Enforces idempotency so duplicate announces caused by retries are discarded.

The announce system prompt instructs the child agent on how to signal completion
to its parent and how to surface errors. Depth and parent context are embedded in
the system prompt at spawn time via `buildSubagentSystemPrompt()`.

### What Synapse-OSS has

No announce flow. If a sub-process were added, there is no delivery mechanism to
route its completion result back to the parent session.

### Gap summary

Even if Synapse-OSS were extended to spawn child agents, there would be no way to
deliver results back to the parent in a reliable, deduplicated, retried manner.

### Implementation notes for porting

1. After a child session completes, resolve its last message and token stats.
2. Construct an "announce" payload: `{child_session_key, output, token_stats, duration_ms}`.
3. Deliver the payload to the parent's session queue with at-least-once semantics
   (retry up to N times with backoff).
4. Use a (run_id, attempt_index) idempotency key to prevent duplicate deliveries.
5. Inject the announce routing instructions into the child agent's system prompt
   at spawn time, mirroring `buildSubagentSystemPrompt()`.

---

## 4. ACP (Agent Coordination Protocol) Binding Layer

### What openclaw has

**Files:**
- `src/agents/acp-spawn.ts` — `acpSpawn()`, spawns a child via the ACP protocol
- `src/agents/acp-spawn-parent-stream.ts` — streams parent-side events while child runs
- `src/agents/subagent-control.ts` — `steerSubagent()`, `killSubagent()`

ACP is an inter-agent wire protocol that allows an orchestrator to:
- Spawn a named child agent and pass it a task.
- Subscribe to the child's output stream in real time.
- Steer the child mid-run by injecting new instructions.
- Kill the child and receive a structured farewell result.

`steerSubagent()` in `subagent-control.ts` can target any registered run by
`sessionKey`, serialize a new turn into its session, and wake the session if it
is idle. This is the mechanism by which the parent can course-correct a stuck
subagent without killing it.

### What Synapse-OSS has

No ACP equivalent. The `SessionActorQueue` only serializes operations on the same
key; there is no protocol for one session to inject instructions into another.

### Gap summary

Synapse-OSS cannot implement orchestrator–worker patterns. There is no way for one
agent to dynamically steer another or receive streaming updates from a child run.

### Implementation notes for porting

1. Define an `ACPMessage` schema: `{type: "spawn" | "steer" | "kill", session_key, payload}`.
2. Extend `SessionActorQueue` to accept externally injected turns (a `steer` message
   that prepends a user turn to the next LLM call).
3. Expose a `steer_agent(session_key, instruction)` coroutine in the gateway that
   routes to the target session's actor queue.
4. For real-time parent streaming, add a publish–subscribe bus (e.g.,
   `asyncio.Queue` per session key) that the parent reads while the child runs.

---

## 5. Subagent Capabilities and Scope Isolation

### What openclaw has

**Files:**
- `src/agents/subagent-capabilities.ts` — `SubagentCapabilities` type
- `src/agents/subagent-attachments.ts` — attachment directory lifecycle
- `src/agents/spawned-context.ts` — `SpawnedContext`, inheritable context from parent

A spawned subagent can be configured with:
- An explicit `model` / `provider` override (different from the parent).
- A restricted tool allowlist (e.g., read-only tools for a research subagent).
- An isolated attachment directory that is cleaned up when the subagent completes.
- A `SpawnedContext` that carries forward parent context (e.g., persona, channel).

This enables specialization: a coding subagent might use a code-focused model with
bash + file tools, while a research subagent uses a web-search model.

### What Synapse-OSS has

`SynapseLLMRouter.call()` accepts a `role` that maps to a model in `model_mappings`.
There is no concept of tool scoping, per-agent model selection, or attachment
lifecycle for child agents.

### Gap summary

Synapse-OSS cannot express "this child agent uses a different model and a
restricted tool set." All agents implicitly share the same model role and tool
access.

### Implementation notes for porting

1. Add a `SpawnConfig` dataclass: `model_role`, `allowed_tools`, `inherited_context`.
2. When dispatching to a child session, filter the tool registry by `allowed_tools`.
3. Create a temporary attachment directory per child run; delete it on completion
   or after a configurable TTL (mirror `safeRemoveAttachmentsDir` in
   `subagent-registry-helpers.ts`).
4. Allow `spawn_config.model_role` to override the session-level model so a
   spawned agent can use a cheaper or more specialized model.
