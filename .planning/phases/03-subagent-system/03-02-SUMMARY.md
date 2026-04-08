---
phase: 03-subagent-system
plan: "02"
subsystem: subagent-runner
tags: [subagents, asyncio, execution-engine, progress, isolation]
dependency_graph:
  requires:
    - 03-01  # SubAgent dataclass, AgentRegistry, AgentStatus models
  provides:
    - SubAgentRunner (spawn + execute sub-agents as isolated asyncio tasks)
    - ProgressReporter (periodic progress callback for long-running agents)
  affects:
    - api_gateway.py (will wire SubAgentRunner singleton at startup)
tech_stack:
  added: []
  patterns:
    - GC-anchor pattern (_agent_tasks/_reporter_tasks module-level sets)
    - asyncio.wait_for timeout wrapping
    - try/except crash isolation boundary
    - TYPE_CHECKING for circular-import-safe type hints
key_files:
  created:
    - workspace/sci_fi_dashboard/subagent/progress.py
    - workspace/sci_fi_dashboard/subagent/runner.py
  modified: []
decisions:
  - "Sub-agents use the 'analysis' role (Gemini Pro) by default — deep reasoning tasks"
  - "ProgressReporter.stop() does not await the cancellation — safe for both sync and async callers"
  - "_format_snapshot() renders each dict as key:value lines, falls back to repr() for non-dict items"
  - "lambda used for ProgressReporter callback in _execute to avoid defining a bound method purely for binding"
metrics:
  duration: "~1 minute"
  completed_date: "2026-04-07"
  tasks_completed: 2
  files_created: 2
  files_modified: 0
requirements_addressed:
  - AGENT-02  # Crash isolation
  - AGENT-03  # Result delivery via channel_registry
  - AGENT-04  # Parallel execution via independent asyncio.Tasks
  - AGENT-05  # Scoped context — snapshot dicts, not live MemoryEngine
  - AGENT-06  # Progress updates via ProgressReporter
---

# Phase 03 Plan 02: SubAgentRunner + ProgressReporter Summary

**One-liner:** Isolated asyncio execution engine with timeout, crash boundary, snapshot-only memory access, and periodic progress callbacks — delivering results via the standard channel_registry path.

## What Was Built

### `subagent/progress.py` — ProgressReporter

A lightweight helper that fires an async callback at a configurable interval to signal that a long-running sub-agent is still alive and working.

Key design choices:
- Module-level `_reporter_tasks: set[asyncio.Task]` GC anchor (same pattern as `pipeline_helpers._background_tasks`) prevents the background loop from being garbage-collected.
- `start()` is a no-op when no callback is provided — safe to use unconditionally.
- `stop()` cancels the internal task and uses `contextlib.suppress(asyncio.CancelledError)` so it is safe to call from both sync and async contexts.
- `update()` fires the callback immediately out-of-band (does not reset the timer) so the agent can surface important milestones right away.
- No heavy imports — callback is injected by SubAgentRunner.

### `subagent/runner.py` — SubAgentRunner

The execution engine that spawns and manages sub-agent asyncio tasks.

Key design choices:
- `spawn_agent()` returns immediately after creating the task — callers are never blocked.
- `_run_agent()` is the crash isolation boundary: `try/except Exception` catches all non-cancellation failures, logs them, calls `registry.fail()`, and delivers a user-facing error message. Parent conversation is never affected (AGENT-02).
- `asyncio.wait_for` wraps `_execute()` with `agent.timeout_seconds` — TimeoutError is caught and converted to a polite user message (AGENT-06).
- `asyncio.CancelledError` is explicitly re-raised per asyncio contract.
- `_execute()` only receives `context_snapshot` and `memory_snapshot` (frozen `list[dict]`) — never a reference to the live MemoryEngine (AGENT-05).
- Multiple `spawn_agent()` calls produce independent asyncio.Tasks — full parallel execution (AGENT-04).
- Results delivered via `channel_registry.get(channel_id).send()` — same path as the parent pipeline (AGENT-03).
- `TYPE_CHECKING` guards on all cross-module imports to avoid circular dependencies at runtime.

## Requirement Coverage

| Requirement | Coverage |
|-------------|----------|
| AGENT-02: Crash isolation | `_run_agent()` try/except boundary |
| AGENT-03: Result delivery | `_deliver_result()` via channel_registry |
| AGENT-04: Parallel execution | Each `spawn_agent()` call creates independent asyncio.Task |
| AGENT-05: Scoped context | Only snapshot dicts passed to `_execute()` |
| AGENT-06: Progress + timeout | ProgressReporter + asyncio.wait_for |

## Commits

| Hash | Message |
|------|---------|
| `92a0eba` | feat(03-02): add ProgressReporter for periodic sub-agent progress updates |
| `4e36575` | feat(03-02): add SubAgentRunner — isolated asyncio sub-agent execution engine |

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `workspace/sci_fi_dashboard/subagent/progress.py` — FOUND
- `workspace/sci_fi_dashboard/subagent/runner.py` — FOUND
- Commit `92a0eba` — FOUND (feat(03-02): add ProgressReporter…)
- Commit `4e36575` — FOUND (feat(03-02): add SubAgentRunner…)
- `_run_agent` contains `except Exception` crash boundary — CONFIRMED
- `asyncio.wait_for` with `agent.timeout_seconds` — CONFIRMED
- No import of MemoryEngine in runner.py — CONFIRMED
- `contextlib.suppress(asyncio.CancelledError)` in ProgressReporter.stop() — CONFIRMED
