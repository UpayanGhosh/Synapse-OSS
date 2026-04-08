---
phase: 03-subagent-system
plan: "04"
subsystem: subagent-tests
tags: [subagents, tests, pytest, asyncio, integration, unit]

# Dependency graph
requires:
  - 03-01  # SubAgent dataclass, AgentRegistry
  - 03-02  # SubAgentRunner, ProgressReporter
  - 03-03  # detect_spawn_intent, maybe_spawn_agent, pipeline wiring
provides:
  - Unit tests: TestSubAgent, TestAgentStatus, TestAgentRegistry, TestProgressReporter, TestSpawnIntentDetection
  - Integration tests: TestSubAgentRunner (parallel timing, crash isolation, progress, delivery)
  - Integration tests: TestMaybeSpawnAgent (str/None return, graceful degradation, memory unwrapping)
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - pytest.mark.asyncio for async integration tests
    - MagicMock(spec=asyncio.Task) for task cancellation assertions
    - FastAPI TestClient with mocked deps singleton for endpoint tests
    - asyncio.sleep() gating to allow background tasks to complete before assertions
    - Module-level deps patching (original/restore pattern) for spawn.py isolation

key-files:
  created:
    - workspace/tests/test_subagent.py
    - workspace/tests/test_subagent_integration.py
  modified: []

key-decisions:
  - "Integration tests patch deps.agent_runner / deps.memory_engine directly at module level using save/restore pattern — avoids complex mock.patch context managers for module globals"
  - "Crash isolation test uses two separate SubAgentRunner instances sharing one AgentRegistry — cleanest way to control per-agent LLM behavior without coupling runners"
  - "Parallel timing test uses asyncio.sleep(1.0) gating after two 0.5s agents, then asserts wall_time < 1.5s — gives 1.5x headroom without risking false failures in slow CI"
  - "GET /agents endpoint test uses FastAPI TestClient with no gateway token configured — matches dev-mode auth skip in _require_gateway_auth when expected token is empty"
  - "ProgressReporter sync tests avoid event-loop dependency by only testing _latest_message storage (no callback), keeping them fast and loop-free"

requirements-completed: [AGENT-02, AGENT-04, AGENT-06, AGENT-07]

# Metrics
duration: ~15min
completed: 2026-04-07
---

# Phase 03 Plan 04: Subagent System Tests Summary

**One-liner:** 396-line unit test suite (SubAgent dataclass, AgentStatus, AgentRegistry CRUD/lifecycle/pruning, ProgressReporter, intent detection) plus 536-line integration test suite (parallel execution timing, crash isolation, progress callbacks, result delivery, API endpoint, spawn orchestration) — all mocked, no live LLM or channel dependencies.

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-04-07
- **Tasks:** 2
- **Files created:** 2
- **Files modified:** 0

## Accomplishments

### Task 1: `workspace/tests/test_subagent.py` — Unit Tests (396 lines)

**class TestSubAgent (4 tests):**
- `test_create_with_defaults` — all default field values verified (status=SPAWNING, result/error/progress=None, timeout=120.0, empty snapshots)
- `test_to_api_dict_serializable` — `json.dumps()` round-trip + status is str + snapshots omitted
- `test_duration_none_when_incomplete` — three scenarios: no timestamps, only started_at, only completed_at
- `test_duration_calculated` — sets started/completed 3.5s apart, asserts within 0.001s tolerance

**class TestAgentStatus (2 tests):**
- All 6 StrEnum values verified (spawning/running/completed/failed/cancelled/timed_out)
- Each status isinstance-str assertion

**class TestAgentRegistry (9 tests):**
- Full CRUD: spawn→get, complete→archive, fail, timeout, cancel
- Archive pruning with archive_ttl_seconds=0 + manual timestamp backdating
- Task cancellation: MagicMock(spec=asyncio.Task) with name convention, cancel() returns True
- list_all() covers both active + archived agents
- Duplicate spawn raises ValueError

**class TestProgressReporter (4 tests):**
- Instantiation without callback, with callback, stop() as no-op
- _latest_message storage (sync path, loop-free)

**class TestSpawnIntentDetection (10 tests):**
- All three detection tiers: SPAWN_PREFIXES, background markers, SPAWN_KEYWORDS
- Edge cases: empty string, whitespace-only, normal conversational message

### Task 2: `workspace/tests/test_subagent_integration.py` — Integration Tests (536 lines)

**class TestSubAgentRunner (6 tests):**
- `test_spawn_returns_immediately` — 2.0s LLM, asserts spawn returns in <0.5s
- `test_parallel_execution_timing` — 2x0.5s agents, wall_time < 1.5s proves parallel
- `test_crash_isolation` — dual runners sharing registry: crash→FAILED, success→COMPLETED
- `test_result_delivery_via_channel` — channel.send() called with correct chat_id and result text
- `test_timeout_handling` — 0.3s timeout, 5.0s LLM → TIMED_OUT + timeout message sent
- `test_progress_updates` — 1.5s LLM, 0.4s interval → ≥2 channel.send() calls

**class TestMaybeSpawnAgent (4 tests):**
- Returns acknowledgment string with "On it!" + task description for spawn messages
- Returns None for non-spawn messages, spawn_agent not called
- Returns None when deps.agent_runner is None (graceful degradation)
- memory_snapshot is the unwrapped `results` list, not the raw query() dict

## Task Commits

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Unit tests | `4b23223` | `workspace/tests/test_subagent.py` (created) |
| 2 | Integration tests | `d2404b2` | `workspace/tests/test_subagent_integration.py` (created) |

## Requirement Coverage

| Requirement | Test |
|-------------|------|
| AGENT-01: Immediate ack after spawn | `test_spawn_returns_immediately` |
| AGENT-02: Crash isolation | `test_crash_isolation` |
| AGENT-03: Result delivery | `test_result_delivery_via_channel` |
| AGENT-04: Parallel execution | `test_parallel_execution_timing` |
| AGENT-06: Progress updates | `test_progress_updates` |
| AGENT-07: GET /agents API | `test_get_agents_endpoint` |

## Deviations from Plan

None — plan executed exactly as written. One minor addition: `test_to_api_dict_omits_snapshots` added as a bonus assertion alongside `test_to_api_dict_serializable` to explicitly verify the snapshot-omission contract documented in 03-01-SUMMARY.md.

## Self-Check: PASSED

- `workspace/tests/test_subagent.py` — FOUND
- `workspace/tests/test_subagent_integration.py` — FOUND
- Commit `4b23223` — FOUND (test(03-04): add unit tests...)
- Commit `d2404b2` — FOUND (test(03-04): add integration tests...)
- `class TestSubAgent` in test_subagent.py — CONFIRMED
- `class TestSubAgentRunner` in test_subagent_integration.py — CONFIRMED
- `from sci_fi_dashboard.subagent.models import AgentStatus, SubAgent` — CONFIRMED
- `from sci_fi_dashboard.subagent.runner import SubAgentRunner` — CONFIRMED

---
*Phase: 03-subagent-system*
*Completed: 2026-04-07*
