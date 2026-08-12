---
phase: 03-subagent-system
plan: 01
subsystem: api
tags: [subagent, asyncio, fastapi, dataclass, registry, lifecycle]

# Dependency graph
requires: []
provides:
  - SubAgent dataclass with full lifecycle fields, duration_seconds property, to_api_dict()
  - AgentStatus StrEnum (spawning/running/completed/failed/cancelled/timed_out)
  - AgentRegistry with spawn/attach_task/get/cancel/complete/fail/timeout/list_all/archive
  - GC anchor pattern (_task_refs set) for asyncio.Task lifecycle management
  - GET /api/agents, GET /api/agents/{id}, POST /api/agents/{id}/cancel endpoints
  - deps.agent_registry singleton initialized in FastAPI lifespan
affects:
  - 03-subagent-system/03-02 (runner — builds on AgentRegistry.attach_task)
  - 03-subagent-system/03-03 (pipeline wiring — spawns agents via registry)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - StrEnum for status enums (Python 3.11 native, no extra deps)
    - Lazy singleton access in route handlers via `from sci_fi_dashboard import _deps as deps` (sessions.py pattern)
    - GC anchor set for asyncio.Task refs — prevents garbage collection of running tasks
    - Lazy archive pruning on list_all() — no background task needed, TTL-based

key-files:
  created:
    - workspace/sci_fi_dashboard/subagent/__init__.py
    - workspace/sci_fi_dashboard/subagent/models.py
    - workspace/sci_fi_dashboard/subagent/registry.py
    - workspace/sci_fi_dashboard/routes/agents.py
  modified:
    - workspace/sci_fi_dashboard/_deps.py
    - workspace/sci_fi_dashboard/api_gateway.py

key-decisions:
  - "AgentRegistry._task_refs is a set (not dict) — GC anchor only, task lookup by name string convention agent-<id>"
  - "Snapshot fields (context_snapshot, memory_snapshot) omitted from to_api_dict() to avoid leaking conversation history over the wire"
  - "agent_registry initialized in lifespan (not at module level in _deps.py) to avoid asyncio issues at import time"
  - "Archive searched by linear scan in get_agent() route — acceptable given low expected archive size"

patterns-established:
  - "AgentRegistry pattern: mirrors ChannelRegistry with dict store + GC anchor set + lifecycle transitions"
  - "Route lazy import pattern: singleton accessed inside handler body via _deps, not at module level"

requirements-completed: [AGENT-01, AGENT-07]

# Metrics
duration: 15min
completed: 2026-04-07
---

# Phase 3 Plan 01: SubAgent Data Model, Registry, and API Endpoints Summary

**SubAgent dataclass with StrEnum lifecycle states, AgentRegistry with GC-anchored asyncio.Task tracking, and three REST endpoints (list/get/cancel) wired into the FastAPI app**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-07T00:00:00Z
- **Completed:** 2026-04-07T00:15:00Z
- **Tasks:** 2
- **Files modified:** 6 (4 created, 2 modified)

## Accomplishments

- `subagent/` package with `SubAgent` dataclass capturing all fields required by AGENT-01 and AGENT-07: identity, lifecycle state, origin (channel/chat/session), frozen context/memory snapshots, timing, result/error, progress, timeout
- `AgentRegistry` with spawn/attach_task/get/cancel/complete/fail/timeout/list_all lifecycle, GC anchor `_task_refs` set, and 1h TTL lazy archive pruning
- Three REST endpoints: `GET /api/agents`, `GET /api/agents/{agent_id}`, `POST /api/agents/{agent_id}/cancel` — all auth-gated via `_require_gateway_auth`, following sessions.py pattern
- `deps.agent_registry` singleton initialized in FastAPI lifespan; routes use lazy import pattern to avoid circular deps

## Task Commits

Each task was committed atomically:

1. **Task 1: Create subagent package with SubAgent dataclass and AgentRegistry** - `cfb6471` (feat)
2. **Task 2: Create GET /agents route and wire into FastAPI app** - `bbda242` (feat)

**Plan metadata:** (pending docs commit)

## Files Created/Modified

- `workspace/sci_fi_dashboard/subagent/__init__.py` — package init, exports SubAgent, AgentStatus, AgentRegistry
- `workspace/sci_fi_dashboard/subagent/models.py` — SubAgent dataclass + AgentStatus StrEnum
- `workspace/sci_fi_dashboard/subagent/registry.py` — AgentRegistry with full lifecycle management
- `workspace/sci_fi_dashboard/routes/agents.py` — GET/POST /api/agents endpoints
- `workspace/sci_fi_dashboard/_deps.py` — added `agent_registry: AgentRegistry | None = None` singleton variable
- `workspace/sci_fi_dashboard/api_gateway.py` — imported agents_routes, wired router, init AgentRegistry in lifespan

## Decisions Made

- `AgentRegistry._task_refs` is a `set[asyncio.Task]` (not dict), functioning purely as a GC anchor. Task cancellation uses `task.get_name()` matching `"agent-<id>"` convention — Plan 02 (runner) must name tasks this way.
- `context_snapshot` and `memory_snapshot` are stored in `SubAgent` but omitted from `to_api_dict()` to avoid leaking conversation history through the API.
- `agent_registry` is initialized in the FastAPI lifespan (not at `_deps.py` module level) to avoid any event-loop-related issues at import time, matching how other optional components (ToolRegistry, safety pipeline) are initialized.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Plan 02 (runner) can import `SubAgent`, `AgentRegistry` from `sci_fi_dashboard.subagent` and `deps.agent_registry` immediately
- Task naming convention for cancellation: tasks must be created as `asyncio.create_task(coro, name=f"agent-{agent.agent_id}")`
- Archive scan in `GET /api/agents/{id}` uses linear search over `registry._archive` — acceptable for expected volumes; Plan 02 can optimize if needed

---
*Phase: 03-subagent-system*
*Completed: 2026-04-07*
