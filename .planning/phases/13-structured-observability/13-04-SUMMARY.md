---
phase: 13
plan: 4
subsystem: observability
tags: [structured-logging, pipeline, llm-router, runid, pii-fix, singleton-race]
dependency_graph:
  requires: [13-01, 13-02, 13-03]
  provides: [pipeline_emitter_race_closed, chat_pipeline_structured_logs, llm_router_structured_logs]
  affects: [chat_pipeline.py, pipeline_emitter.py, llm_router.py]
tech_stack:
  added: []
  patterns: [get_child_logger, ContextVar-backfeed, structured-extra-dict]
key_files:
  modified:
    - workspace/sci_fi_dashboard/pipeline_emitter.py
    - workspace/sci_fi_dashboard/chat_pipeline.py
    - workspace/sci_fi_dashboard/llm_router.py
decisions:
  - "Removed .encode('ascii','replace') intermediates from chat_pipeline: JsonFormatter ensure_ascii=True provides the same Windows cp1252 protection at serialization time"
  - "llm_router: added import time (was missing); added _log with ImportError guard for circular-import safety"
  - "Did NOT refactor the 40+ existing logger.* calls in llm_router — only added llm_call_done emit. Full migration deferred to a follow-up plan."
  - "pipeline_emitter singleton _current_run_id kept for SSE emit() payload backward compat — it is now derived from ContextVar, not the source of truth"
metrics:
  duration: ~20min
  completed: 2026-04-22
  tasks: 5
  files: 3
---

# Phase 13 Plan 4: Pipeline Emitter Race Fix + chat_pipeline/llm_router Structured Logger Migration Summary

Closed the PipelineEventEmitter singleton race and migrated chat_pipeline.py off bare print()/logger calls to a ContextVar-aware structured logger; added minimal structured emit to llm_router.

## What Was Built

### Task 1: pipeline_emitter singleton race fix (5-line change)

`start_run()` previously minted a fresh `uuid.uuid4().hex[:12]` on every call, overwriting `self._current_run_id`. Two concurrent `persona_chat()` invocations would trample each other's runId in the singleton — SSE dashboard events got tagged with the wrong conversation's runId.

Fix: `rid = run_id or get_run_id() or mint_run_id()`

The ContextVar is task-local in asyncio, so each concurrent call reads its own value without interference. The `self._current_run_id` field is kept only for `emit()` payload backward compat with SSE dashboard consumers; it is now derived (not the source of truth).

The `import uuid` line was removed (no longer used). `get_run_id` and `mint_run_id` are imported from `sci_fi_dashboard.observability`.

Commit: `44ba921`

### Task 2: chat_pipeline.py structured logger migration

Added `from sci_fi_dashboard.observability import get_child_logger` and:
```python
_log = get_child_logger("pipeline.chat")  # OBS-01 structured logger carrying runId
```

Removed `_tool_logger = logging.getLogger(__name__ + ".tools")` (now unused).

**PII leak fixed (T-13-PII-03):** Line 99 `print(f"[MAIL] [{target.upper()}] Inbound: {user_msg[:80]}...")` replaced with:
```python
_log.info("inbound_message", extra={"target": target, "msg_preview": user_msg[:40], "chat_id": ...})
```
Preview truncated from 80 to 40 chars. JsonFormatter handles chat_id sensitivity.

**Total print() calls migrated: 25 sites** (0 remaining — complete migration)

Events emitted:
- `inbound_message` — webhook entry with truncated preview
- `consent_expired`, `consent_confirmed`, `consent_sender_mismatch`, `consent_declined`, `consent_pending`
- `memory_engine_error` — memory retrieval failure
- `toxicity_high_safe_mode` — with toxicity score field
- `cognitive_state` — tension_type + tension_level
- `inner_thought` — inner_monologue[:100] preview
- `dual_cognition_timeout`, `dual_cognition_failed`
- `skill_routed` — skill_name field
- `vault_route` — hemisphere=spicy
- `vault_failed` — error + cloud_fallback=blocked
- `traffic_cop_skip` — strategy + mapped_role
- `model_override`, `image_gen_disabled`, `image_gen_vault_blocked`, `image_gen_empty`, `image_gen_channel_missing_send_media`, `image_gen_background_failed`, `image_gen_no_background_tasks`
- `route_classified` — classification + role
- `tool_loop_context_overflow`, `tool_loop_rate_limited`, `tool_loop_llm_error`, `tool_result_limit`, `tool_loop_exhausted`, `tool_loop_done`
- `response_generated` — target + model + reply_preview[:60]
- `auto_continue_triggered`, `auto_continue_no_background_tasks`

The `.encode("ascii", errors="replace").decode()` intermediate variables (`_safe_preview`, `_safe_thought`) were removed. JsonFormatter's `ensure_ascii=True` provides the same Windows cp1252 safety at serialization time.

Commit: `2832fe1`

### Task 3: llm_router.py minimal structured emit

Added `import time` (was missing from stdlib imports).

Added child logger near existing `logger = logging.getLogger(__name__)`:
```python
try:
    from sci_fi_dashboard.observability import get_child_logger as _get_child_logger
    _log = _get_child_logger("llm.router")
except ImportError:
    _log = logger  # type: ignore[assignment]
```

Added one `_log.info("llm_call_done", ...)` emission in `call_with_metadata` just before the final return, carrying: `role`, `model`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `latency_ms`.

Did NOT migrate the 40+ existing `logger.*` calls in llm_router — those are stable, non-PII, and safe. Full migration flagged for a future plan. Plan 13-05 wires up per-module config so operators can set `logging.modules.llm.router: DEBUG` to see these emissions at runtime.

Commit: `2832fe1`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Missing import] `time` not imported in llm_router.py**
- **Found during:** Task 3, ruff lint check
- **Issue:** `time.time()` used in new `llm_call_done` emit but `import time` was absent from llm_router.py stdlib imports
- **Fix:** Added `import time` to the stdlib import block (alphabetical order between `sys` and `uuid`)
- **Files modified:** `workspace/sci_fi_dashboard/llm_router.py`
- **Commit:** `2832fe1`

## Test Results

| Test | Result |
|------|--------|
| `test_concurrent_runs_isolated` | PASSED |
| `test_end_to_end_run_id` | PASSED |
| `test_flood_batch_last_wins` | PASSED |
| `test_worker_inherits_task_run_id` | PASSED |
| `test_all_hops_share_run_id` | PASSED |
| Full OBS suite (14 tests) | 14/14 PASSED |
| llm_router test suite (99 tests) | 98/99 PASSED (1 pre-existing failure: `test_github_copilot_prefix` — unrelated to this plan) |

## Known Stubs

None — all log events emit real runtime data. No placeholder/TODO values in extra dicts.

## Threat Flags

All three STRIDE threats from the plan were mitigated:

| Threat | Status |
|--------|--------|
| T-13-CTXLEAK-02: PipelineEventEmitter._current_run_id singleton race | Mitigated — ContextVar backfeed |
| T-13-PII-03: `[MAIL] Inbound` raw print (80-char preview) | Mitigated — _log.info with 40-char truncation |
| T-13-PII-04: 12+ print() sites in chat_pipeline | Mitigated — all 25 migrated, 0 remaining |

No new trust-boundary surface introduced.

## Self-Check: PASSED

- `workspace/sci_fi_dashboard/pipeline_emitter.py` — exists, contains `get_run_id() or mint_run_id()`
- `workspace/sci_fi_dashboard/chat_pipeline.py` — exists, contains `get_child_logger("pipeline.chat")`, 0 print() calls
- `workspace/sci_fi_dashboard/llm_router.py` — exists, contains `get_child_logger("llm.router")` and `llm_call_done`
- Commits `44ba921` and `2832fe1` verified in git log
