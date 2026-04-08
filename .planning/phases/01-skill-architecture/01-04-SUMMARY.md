---
phase: 01-skill-architecture
plan: "04"
subsystem: skills
tags: [skill-runner, pipeline-integration, exception-isolation, lifespan, hot-reload, tdd]

# Dependency graph
requires:
  - phase: 01-skill-architecture
    plan: "01"
    provides: "SkillManifest frozen dataclass, SkillValidationError, SkillLoader"
  - phase: 01-skill-architecture
    plan: "02"
    provides: "SkillRegistry thread-safe singleton, SkillWatcher hot-reload, _deps.py stub"
  - phase: 01-skill-architecture
    plan: "03"
    provides: "SkillRouter embedding-based intent matching"
provides:
  - SkillRunner static class — LLM execution engine with full exception isolation (SKILL-06)
  - SkillResult dataclass — text, skill_name, error flag, execution_ms
  - skills/__init__.py consolidated exports (all 8 public classes)
  - _deps.py updated with _SKILL_SYSTEM_AVAILABLE + skill_registry/router/watcher singletons
  - api_gateway.py lifespan: SkillRegistry scans, SkillRouter embeds, SkillWatcher watches
  - chat_pipeline.py: skill routing intercept before traffic cop
  - Hot-reload: watcher reload() also calls SkillRouter.update_skills()
affects: [api-gateway, chat-pipeline, skill-dispatch]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Exception isolation pattern: static execute() catches ALL exceptions, returns SkillResult(error=True)"
    - "Skills bypass pattern: matched skills return early from persona_chat before MoA pipeline"
    - "Non-fatal init pattern: skill system init wrapped in try/except; server starts normally on failure"
    - "Privacy boundary: session_mode != spicy guards ALL skill routing (T-01-14)"
    - "Hot-reload chaining: watcher.reload() monkey-patched to also call router.update_skills()"

key-files:
  created:
    - workspace/sci_fi_dashboard/skills/runner.py
    - workspace/tests/test_skill_pipeline.py
  modified:
    - workspace/sci_fi_dashboard/skills/__init__.py
    - workspace/sci_fi_dashboard/_deps.py
    - workspace/sci_fi_dashboard/api_gateway.py
    - workspace/sci_fi_dashboard/chat_pipeline.py

key-decisions:
  - "SkillRunner uses only static methods — no instance state needed; avoids singleton overhead"
  - "Exception isolation wraps the ENTIRE LLM call chain — any exception (network, timeout, provider) is caught"
  - "Skills intercept BEFORE traffic cop, AFTER message assembly — skill has full context including history"
  - "Memory stored via add_memory() (correct API, NOT store()) — explicitly noted in code comment"
  - "Hot-reload monkey-patches registry.reload() to also update router — avoids adding a callback parameter to SkillRegistry"
  - "api_gateway.py skills.router include added alongside existing route includes (no duplicate)"
  - "Pipeline integration tests use _make_dual_cognition_mock() helper — trajectory.get_summary() must return '' not MagicMock"

requirements-completed:
  - SKILL-06

# Metrics
duration: 30min
completed: 2026-04-07
---

# Phase 01 Plan 04: Skill Architecture — Pipeline Integration Summary

**SkillRunner with exception isolation + full pipeline wiring — 12 tests passing**

## Performance

- **Duration:** ~30 min
- **Completed:** 2026-04-07
- **Tasks:** 2 (Task 1: TDD RED + GREEN for SkillRunner; Task 2: wiring integration)
- **Files modified:** 4 modified, 2 created

## Accomplishments

- `SkillRunner` static class with `execute()` coroutine — full exception isolation (SKILL-06)
  - Uses `manifest.instructions` as system prompt; fallback to `name + description` when empty
  - Uses `manifest.model_hint` as LLM role; fallback to `"casual"` when unset
  - Catches ALL exceptions: network errors, timeouts, provider failures — returns `SkillResult(error=True)` with user-friendly message
  - Records `execution_ms` for observability
- `SkillResult` dataclass: `text`, `skill_name`, `error: bool`, `execution_ms: float`
- `skills/__init__.py` consolidated: all 8 public classes exported (SkillManifest, SkillValidationError, SkillLoader, SkillRegistry, SkillWatcher, SkillRouter, SkillRunner, SkillResult)
- `_deps.py` updated: `_SKILL_SYSTEM_AVAILABLE` flag + `skill_registry`, `skill_router`, `skill_watcher` singletons (all `None` until lifespan init)
- `api_gateway.py` lifespan: skill system initialized after CronService; non-fatal try/except wraps entire init; SkillWatcher started + stopped in lifespan; `skills.router` included for GET /skills endpoint
- `chat_pipeline.py` routing intercept: before traffic cop block, after full message assembly; `session_mode != "spicy"` guard enforces privacy boundary (T-01-14); matched skills bypass MoA entirely; unmatched messages fall through unchanged; memory stored via `add_memory()` (correct API)
- Hot-reload chain: `SkillWatcher` triggers `registry.reload()` which is monkey-patched to also call `router.update_skills()` — new skills become routable without restart
- 12 tests: 8 SkillRunner unit + 4 pipeline integration (all passing)

## Task Commits

1. **TDD RED — failing tests for SkillRunner and pipeline integration** - `6304fcb` (test)
2. **TDD GREEN — implement SkillRunner** - `0b40ffe` (feat)
3. **Wire skill system into pipeline** - `aac5396` (feat)

## Files Created/Modified

- `workspace/sci_fi_dashboard/skills/runner.py` — SkillRunner class, SkillResult dataclass
- `workspace/tests/test_skill_pipeline.py` — 12 tests: 8 runner unit + 4 pipeline integration
- `workspace/sci_fi_dashboard/skills/__init__.py` — consolidated exports from Plans 01-04
- `workspace/sci_fi_dashboard/_deps.py` — _SKILL_SYSTEM_AVAILABLE + skill singletons
- `workspace/sci_fi_dashboard/api_gateway.py` — lifespan skill init + skills router include
- `workspace/sci_fi_dashboard/chat_pipeline.py` — skill routing intercept before traffic cop

## Decisions Made

- `SkillRunner.execute()` is a `@staticmethod` — no instance state needed; avoids singleton pattern overhead and matches `SkillLoader` convention established in Plan 01
- Exception isolation covers the entire `llm_router.call()` chain — not just `RuntimeError`; any `Exception` subclass is caught so network timeouts, API errors, and unexpected failures all produce graceful degradation
- The skill routing intercept is placed AFTER full message assembly but BEFORE the traffic cop block — skills receive the full context (persona system prompt, memory context, cognitive context) but bypass the MoA routing decision entirely
- Memory stored via `deps.memory_engine.add_memory(content=..., category="skill_execution")` — the plan explicitly notes the correct API (NOT `store()`) to prevent a known gotcha
- Hot-reload implemented by monkey-patching `registry.reload` rather than adding a callback parameter to `SkillRegistry` — avoids changing the Plan 02 API surface that other callers depend on

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pipeline integration test mocks returned MagicMock instead of str for trajectory**

- **Found during:** Task 2 (pipeline integration test execution)
- **Issue:** `mock_deps.dual_cognition = MagicMock()` creates a mock where `.trajectory` is truthy and `.trajectory.get_summary()` returns a `MagicMock` object. When `chat_pipeline.py` line 323 does `"\n\n".join(p for p in [cognitive_context, _trajectory_summary] if p)`, the filter `if p` passes (MagicMock is truthy) and `str.join` fails with `TypeError: sequence item 0: expected str instance, MagicMock found`.
- **Fix:** Added `_make_dual_cognition_mock()` helper that explicitly sets `.trajectory.get_summary.return_value = ""`. Applied to all 4 integration tests via a shared `_base_deps()` method.
- **Files modified:** workspace/tests/test_skill_pipeline.py
- **Commit:** aac5396

## Known Stubs

None — all pipeline wiring is fully functional. The `_deps.py` attributes are intentionally `None` at module load time; they are set to real instances during lifespan. This is not a stub — it is the correct initialization pattern.

## Threat Flags

None — no new network endpoints introduced. The skill routing intercept is in the existing `persona_chat()` path. The threat model mitigations from the plan are implemented:

- T-01-11: `session_mode != "spicy"` guard prevents skill routing in vault hemisphere
- T-01-13: Full exception isolation at `SkillRunner.execute()` boundary
- T-01-14: Spicy hemisphere check verified by `test_pipeline_spicy_session_skips_skill_routing`
- T-01-15: Non-fatal init: entire skill system init wrapped in try/except; `deps.skill_registry/router/watcher` set to `None` on failure

---
*Phase: 01-skill-architecture*
*Completed: 2026-04-07*

## Self-Check: PASSED

- FOUND: workspace/sci_fi_dashboard/skills/runner.py
- FOUND: workspace/tests/test_skill_pipeline.py
- FOUND: workspace/sci_fi_dashboard/skills/__init__.py
- FOUND: workspace/sci_fi_dashboard/_deps.py
- FOUND: workspace/sci_fi_dashboard/api_gateway.py
- FOUND: workspace/sci_fi_dashboard/chat_pipeline.py
- FOUND: .planning/phases/01-skill-architecture/01-04-SUMMARY.md
- FOUND: commit 6304fcb (TDD RED — failing tests)
- FOUND: commit 0b40ffe (TDD GREEN — SkillRunner implementation)
- FOUND: commit aac5396 (pipeline wiring — all 5 files)
- Tests: 12 passed in 2.35s
