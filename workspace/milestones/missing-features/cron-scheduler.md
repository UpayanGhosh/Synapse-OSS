# Cron Scheduler — Gaps in Synapse-OSS

## Overview

openclaw has a production-grade cron service (`src/cron/`) with three schedule kinds (absolute, every-N-ms, cron expression), isolated-agent job execution, delivery routing to any channel, failure alerting, per-job state persistence, stagger windows, top-of-hour jitter, and a full test suite of 60+ tests covering edge cases. Synapse-OSS has a `ProactiveAwarenessEngine` that polls MCP servers at a fixed interval — it is not a general-purpose scheduler and cannot schedule arbitrary agent turns.

---

## What openclaw Has

### 1. Three Schedule Kinds (`src/cron/types.ts`)

```typescript
type CronSchedule =
  | { kind: "at"; at: string }           // one-shot at ISO timestamp
  | { kind: "every"; everyMs: number; anchorMs?: number }  // fixed interval
  | { kind: "cron"; expr: string; tz?: string; staggerMs?: number }  // cron expression
```

`"at"` jobs automatically disable themselves after firing (one-shot). `"every"` jobs use `anchorMs` for deterministic scheduling regardless of startup time. `"cron"` jobs use the `croner` library with timezone support and a `staggerMs` window for jitter within a time band.

**File:** `src/cron/types.ts`

### 2. Cron Expression Parser + Cache (`src/cron/schedule.ts`)

- `croner` library for POSIX cron expression evaluation with timezone.
- LRU eval cache (`CRON_EVAL_CACHE_MAX = 512`) — avoids re-parsing the same expression on every tick.
- `computeNextRunAtMs(schedule, nowMs)` — unified next-run computation for all three schedule kinds.
- `coerceFiniteScheduleNumber` — safe number coercion for `everyMs` and `atMs` fields.

**File:** `src/cron/schedule.ts`

### 3. Job Store (`src/cron/store.ts`, `store-migration.ts`)

- JSON file at `~/.openclaw/{agentDir}/cron.json` — `CronStoreFile {version: 1; jobs: CronJob[]}`.
- Atomic write (temp + rename).
- `store-migration.ts` — upgrades `atMs` (legacy number) → `at` (ISO string) format automatically on load.
- `CronJobState` persisted per job: `nextRunAtMs`, `lastRunAtMs`, `lastRunStatus`, `lastError`, `lastDurationMs`, `consecutiveErrors`, `lastFailureAlertAtMs`, `scheduleErrorCount`, `lastDeliveryStatus`.

**Files:** `src/cron/store.ts`, `src/cron/store-migration.ts`

### 4. CronService API (`src/cron/service.ts` + `service/`)

```typescript
class CronService {
  start(): Promise<void>
  stop(): void
  status(): Promise<CronServiceStatus>
  list(opts?): Promise<CronJob[]>
  listPage(opts?): Promise<CronListPageResult>
  add(input: CronJobCreate): Promise<CronJob>
  update(id, patch: CronJobPatch): Promise<CronJob>
  remove(id): Promise<void>
  run(id, mode?: "due" | "force"): Promise<CronRunResult>
  enqueueRun(id, mode?): Promise<void>
}
```

`service/ops.ts` — all operations against the mutable service state.
`service/timer.ts` — arm/rearm timer. Prevents tight loops when `armTimer` is called while a job is running.
`service/locked.ts` — per-job mutex to prevent duplicate concurrent executions.
`service/normalize.ts` — normalizes job patches into valid job state.

**Files:** `src/cron/service.ts`, `src/cron/service/`

### 5. Payload Kinds (`src/cron/types.ts`)

```typescript
type CronPayload =
  | { kind: "systemEvent"; text: string }   // synthetic system message
  | { kind: "agentTurn" } & {               // full agent inference turn
      message: string;
      model?: string;           // per-job model override
      fallbacks?: string[];     // per-job fallback chain override
      thinking?: string;
      timeoutSeconds?: number;
      allowUnsafeExternalContent?: boolean;
      lightContext?: boolean;   // lightweight bootstrap context
      toolsAllow?: string[];    // tool allow-list for this job
      deliver?: boolean;
      channel?: CronMessageChannel;
      to?: string;
      bestEffortDeliver?: boolean;
    }
```

`agentTurn` jobs run a full inference loop with all agent tools available. `systemEvent` jobs inject a system message without invoking the model.

### 6. Session Targets (`src/cron/types.ts`)

```typescript
type CronSessionTarget = "main" | "isolated" | "current" | `session:${string}`
```

- `"main"` — runs in the agent's main session.
- `"isolated"` — runs in a fresh ephemeral session, cleaned up after.
- `"current"` — runs in the session that last interacted with the agent.
- `"session:<key>"` — runs in a specific named session.

`isolated-agent.ts` — full isolated agent execution with heartbeat, delivery awareness, sub-agent model override, and failover reason tracking.

**File:** `src/cron/isolated-agent.ts`

### 7. Delivery Routing (`src/cron/delivery.ts`, `src/cron/service/initial-delivery.ts`)

`CronDelivery`:
```typescript
type CronDelivery = {
  mode: "none" | "announce" | "webhook";
  channel?: CronMessageChannel;  // channelId or "last"
  to?: string;
  accountId?: string;
  bestEffort?: boolean;
  failureDestination?: CronFailureDestination;
}
```

- `"announce"` — sends job output to the configured channel.
- `"webhook"` — HTTP POST to a URL.
- `"last"` channel — routes to the most recently active channel.
- `accountId` — supports multi-account channel setups (e.g. two Telegram bots).
- `bestEffort` — does not fail the job if delivery fails.
- `failureDestination` — separate channel/webhook for failure notifications.

**File:** `src/cron/delivery.ts`

### 8. Failure Alerting (`src/cron/service/jobs.ts`, `heartbeat-policy.ts`)

`CronFailureAlert`:
```typescript
type CronFailureAlert = {
  after?: number;         // consecutive error threshold before alerting
  channel?: CronMessageChannel;
  to?: string;
  cooldownMs?: number;    // minimum interval between alerts
  mode?: "announce" | "webhook";
  accountId?: string;
}
```

- Alert suppressed while `consecutiveErrors < after`.
- `cooldownMs` prevents alert spam if a job fails repeatedly.
- `lastFailureAlertAtMs` persisted in job state for cooldown gating.
- Heartbeat policy: healthy heartbeat suppresses the "heartbeat ok" summary to reduce noise.

**Files:** `src/cron/service/jobs.ts`, `src/cron/heartbeat-policy.ts`

### 9. Top-of-Hour Stagger (`src/cron/stagger.ts`)

For cron jobs that run at the top of the hour, openclaw adds a per-job deterministic stagger based on a hash of the job ID. This prevents thundering-herd when many hourly cron jobs fire simultaneously.

`service.jobs.top-of-hour-stagger.test.ts` verifies the stagger behavior.

**File:** `src/cron/stagger.ts`

### 10. Restart Catch-Up (`src/cron/service/state.ts`)

On service start: jobs whose `nextRunAtMs` is in the past and whose `wakeMode` is `"now"` are run immediately. Jobs with `wakeMode: "next-heartbeat"` are rescheduled to their next future time. Prevents double-fires while still catching up missed runs.

**File:** `src/cron/service/state.ts`

### 11. Run Log + Retention (`src/cron/run-log.ts`, `src/cron/service/store.ts`)

- Per-job run log with configurable retention (days).
- `service.store.migration.ts` — migrates the run log schema.
- Config: `cron.retention.days`, `cron.retention.maxRuns`.

**File:** `src/cron/run-log.ts`

---

## What Synapse-OSS Has

`workspace/sci_fi_dashboard/proactive_engine.py` — `ProactiveAwarenessEngine`:

- Fixed-interval polling of MCP servers (calendar, Gmail, Slack).
- Assembles a `ProactiveContext` with calendar events, unread emails, Slack mentions.
- `compile_prompt_block()` — formats context as a text block injected into the system prompt.
- `has_urgent_items()` — simple threshold check.
- No scheduling syntax (no cron expressions, no one-shot times).
- No job persistence.
- No delivery routing.
- No failure alerting.
- No isolated agent execution.
- No per-job model overrides.

| Feature | Synapse-OSS | openclaw |
|---|---|---|
| Schedule kinds | Fixed interval only | at / every / cron expression |
| Cron expression syntax | None | Full POSIX + timezone |
| One-shot jobs | None | Yes (`"at"` kind, auto-disable) |
| Job persistence | None (in-memory only) | JSON file with state |
| Per-job state (errors, timing) | None | Full (`CronJobState`) |
| Isolated agent execution | None | Full (`isolated-agent.ts`) |
| Delivery routing | None | Channel / webhook |
| Failure alerting | None | Yes (threshold + cooldown) |
| Per-job model override | None | Yes |
| Per-job tool allow-list | None | Yes |
| Top-of-hour stagger | None | Yes |
| Restart catch-up | None | Yes |
| Run log + retention | None | Yes |
| CRUD API | None | Full (add/update/remove/list/run) |

---

## Gap Summary

Synapse-OSS has no general-purpose cron scheduler. The `ProactiveAwarenessEngine` polls MCP context sources at a fixed interval for injection into system prompts — it cannot schedule agent turns, route outputs to channels, alert on failures, or persist job state across restarts.

---

## Implementation Notes for Porting

1. **Job model** — Create `CronJob` dataclass with `id` (UUID), `schedule` (union type), `payload` (systemEvent or agentTurn), `delivery`, `failure_alert`, `state`, `enabled`.

2. **Schedule kinds** — Use `croniter` (Python) for cron expression evaluation with TZ. For `"every"`: compute `anchor_ms + ceil((now - anchor_ms) / every_ms) * every_ms`. For `"at"`: parse ISO string with `datetime.fromisoformat`.

3. **Persistence** — Store jobs in `~/.synapse/cron.json` with atomic write (temp + `os.replace`).

4. **Service loop** — `asyncio` task that wakes at the next `min(job.next_run_at_ms)` using `asyncio.sleep`. On wake: collect all due jobs, run them concurrently with `asyncio.gather`. Rearm timer after each batch.

5. **Isolated agent execution** — For `agentTurn` jobs: create a new `SessionActor` (or equivalent), run inference, collect output, deliver to channel.

6. **Delivery** — For `"announce"` mode: call the appropriate channel adapter's send method. For `"webhook"`: POST with `httpx`.

7. **Failure alerting** — Track `consecutive_errors` per job. When threshold is crossed and cooldown has expired: send alert via delivery channel.
