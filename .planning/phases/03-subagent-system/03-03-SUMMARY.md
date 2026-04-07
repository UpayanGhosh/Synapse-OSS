---
phase: 03-subagent-system
plan: "03"
subsystem: subagent-pipeline
tags: [subagents, intent-detection, spawn-orchestration, pipeline-wiring, asyncio]

# Dependency graph
requires:
  - 03-01  # SubAgent dataclass, AgentRegistry
  - 03-02  # SubAgentRunner, ProgressReporter
provides:
  - detect_spawn_intent() — keyword gate in subagent/intent.py
  - maybe_spawn_agent() — spawn orchestration in subagent/spawn.py
  - Spawn interception in process_message_pipeline (pipeline_helpers.py Step 2b)
  - deps.agent_runner singleton initialized in FastAPI lifespan
affects:
  - workspace/sci_fi_dashboard/pipeline_helpers.py (spawn interception added)
  - workspace/sci_fi_dashboard/_deps.py (agent_runner singleton declared)
  - workspace/sci_fi_dashboard/api_gateway.py (SubAgentRunner init in lifespan)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Conservative keyword gate pattern — prefix + inline marker + keyword matching
    - Fire-and-forget spawn pattern — maybe_spawn_agent returns str|None, pipeline short-circuits
    - memory_engine.query() dict unwrapping — .get("results", []) to extract list
    - Deferred import pattern — spawn module imported inside pipeline step to avoid circular deps

key-files:
  created:
    - workspace/sci_fi_dashboard/subagent/intent.py
    - workspace/sci_fi_dashboard/subagent/spawn.py
  modified:
    - workspace/sci_fi_dashboard/_deps.py
    - workspace/sci_fi_dashboard/api_gateway.py
    - workspace/sci_fi_dashboard/pipeline_helpers.py

key-decisions:
  - "Spawn interception lives in process_message_pipeline() (has chat_id/session_key), NOT in persona_chat() (which only has ChatRequest with no channel/session fields)"
  - "channel_id hardcoded to 'whatsapp' in pipeline_helpers with TODO(multi-channel) comment — tracked tech debt for when a second channel gains pipeline access"
  - "maybe_spawn_agent() returns str|None — None means continue normal pipeline, str means short-circuit with acknowledgment"
  - "memory_engine.query() returns dict not list — correctly unwrapped via .get('results', [])"
  - "spawn.py is an independently importable and testable module — no coupling to chat_pipeline or ChatRequest"

# Metrics
duration: ~10min
completed: 2026-04-07
---

# Phase 03 Plan 03: Spawn Intent Detection + Pipeline Wiring Summary

**One-liner:** Conservative keyword gate (intent.py) feeds a fire-and-forget spawn orchestrator (spawn.py) hooked into process_message_pipeline's Step 2b — "research X" delegates to a background agent with frozen context and memory snapshots, while all non-spawn messages flow unchanged.

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-04-07
- **Tasks:** 3
- **Files created:** 2
- **Files modified:** 3

## Accomplishments

### Task 1: subagent/intent.py — Spawn intent detector

`detect_spawn_intent(message: str) -> tuple[bool, str]` applies a three-tier keyword gate:

1. **SPAWN_PREFIXES** (multi-word, highest specificity) — "can you research", "go research", "look up and summarize", etc.
2. **Background markers** ("in the background", "in background") — presence anywhere in the message.
3. **SPAWN_KEYWORDS** (prefix match) — "research", "look up", "investigate", "find out", etc.

Returns `(True, task_description)` on match, `(False, "")` otherwise. No LLM calls — pure string matching. Conservative by design: false negatives are acceptable, false positives are not.

### Task 2: subagent/spawn.py — Spawn orchestration module

`maybe_spawn_agent(user_msg, chat_id, channel_id, session_key) -> str | None`:

- Checks `deps.agent_runner is None` — graceful degradation if system not initialized.
- Calls `detect_spawn_intent()` — exits early with `None` for non-spawn messages.
- Snapshots last 10 conversation turns from `deps.conversation_cache`.
- Queries `deps.memory_engine.query(task_desc, limit=5)` and correctly unwraps the dict result via `.get("results", [])` — critical correctness fix per the plan's Issue #3.
- Constructs `SubAgent` dataclass and calls `await deps.agent_runner.spawn_agent(agent)`.
- Returns acknowledgment string: "On it! I've started working on that in the background..."

### Task 3: Singleton wiring and pipeline interception

**_deps.py:** Added `agent_runner: "_SubAgentRunner | None" = None` module-level declaration (alongside existing `agent_registry`). Import uses `SubAgentRunner as _SubAgentRunner` to follow the existing aliasing convention in that module.

**api_gateway.py:** In lifespan, after `AgentRegistry()` creation, now also initializes:
```python
deps.agent_runner = SubAgentRunner(
    registry=deps.agent_registry,
    channel_registry=deps.channel_registry,
    llm_router=deps.synapse_llm_router,
)
```

**pipeline_helpers.py:** Step 2b added in `process_message_pipeline()`, between session key build and session store fetch:
```python
from sci_fi_dashboard.subagent.spawn import maybe_spawn_agent
# TODO(multi-channel): channel_id hardcoded — thread from MessageTask when 2nd channel lands
spawn_reply = await maybe_spawn_agent(user_msg, chat_id, "whatsapp", session_key)
if spawn_reply is not None:
    return spawn_reply
```
The `return spawn_reply` is a `str` — matches `process_message_pipeline()`'s `str` return type exactly. `persona_chat()` is never called for spawn messages, and its `dict` return contract is never touched.

## Task Commits

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Spawn intent detector | `922e626` | `subagent/intent.py` (created) |
| 2 | Spawn orchestration module | `d809abd` | `subagent/spawn.py` (created) |
| 3 | Singleton wiring + pipeline interception | `9e55671` | `_deps.py`, `api_gateway.py`, `pipeline_helpers.py` |

## Requirement Coverage

| Requirement | Coverage |
|-------------|----------|
| AGENT-01: "research X" spawns agent + immediate ack | `detect_spawn_intent` + `maybe_spawn_agent` ack string |
| AGENT-03: Result delivered via channel_registry | SubAgentRunner._deliver_result() (Plan 02) |
| AGENT-05: Frozen context_snapshot + memory_snapshot | context_snap (last 10 msgs) + memory_snap (unwrapped query results) |

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `workspace/sci_fi_dashboard/subagent/intent.py` — FOUND
- `workspace/sci_fi_dashboard/subagent/spawn.py` — FOUND
- Commit `922e626` — feat(03-03): add spawn intent detector
- Commit `d809abd` — feat(03-03): add spawn orchestration module
- Commit `9e55671` — feat(03-03): wire subagent singletons and spawn interception
- `detect_spawn_intent` in intent.py — CONFIRMED
- `maybe_spawn_agent` in spawn.py — CONFIRMED
- `agent_runner` in _deps.py — CONFIRMED (line 268)
- `SubAgentRunner` in api_gateway.py lifespan — CONFIRMED (line 177-180)
- `maybe_spawn_agent` in pipeline_helpers.py — CONFIRMED (lines 332-345)
- `detect_spawn_intent` NOT in chat_pipeline.py — CONFIRMED (persona_chat untouched)
- `mem_results.get("results"` in spawn.py — CONFIRMED (memory unwrapping correct)
- `TODO(multi-channel)` comment in pipeline_helpers.py — CONFIRMED

---
*Phase: 03-subagent-system*
*Completed: 2026-04-07*
