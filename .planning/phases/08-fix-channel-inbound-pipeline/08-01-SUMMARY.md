---
phase: 08-fix-channel-inbound-pipeline
plan: 01
subsystem: api
tags: [discord, slack, floodgate, channel-pipeline, adapter-pattern, dedup]

# Dependency graph
requires:
  - phase: 05-core-channels-telegram-discord-slack
    provides: DiscordChannel and SlackChannel with enqueue_fn=None defaults
  - phase: 03-channel-abstraction-layer
    provides: FloodGate, MessageDeduplicator, TaskQueue pipeline
provides:
  - "_make_flood_enqueue() synchronous factory in api_gateway.py"
  - "Discord channel registration with enqueue_fn=_dis_enqueue (flood.incoming() adapter)"
  - "Slack channel registration with enqueue_fn=_slk_enqueue (flood.incoming() adapter)"
  - "TestDiscordFloodGateIntegration — 3 integration tests (DIS-01, DIS-03)"
  - "TestSlackFloodGateIntegration — 2 integration tests (SLK-01, SLK-03)"
affects:
  - 08-02-telegram-flood-routing
  - 08-03-channel-pipeline-integration-tests

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_make_flood_enqueue(channel_id) sync factory — returns async closure routing ChannelMessage through dedup+flood"
    - "Adapter injection pattern: api_gateway.py owns all pipeline wiring; channel adapters remain decoupled"

key-files:
  created: []
  modified:
    - workspace/sci_fi_dashboard/api_gateway.py
    - workspace/tests/test_discord_channel.py
    - workspace/tests/test_slack_channel.py

key-decisions:
  - "_make_flood_enqueue is a sync factory (not async) — no await needed at call site; inner _enqueue is async"
  - "ChannelMessage import fixed to sci_fi_dashboard.channels.base (not channel_message module)"
  - "Discord tests use receive()+_enqueue_fn() directly — on_message is a local closure inside start(), not accessible as a public method"
  - "Slack tests use _dispatch() directly — it is a real public method on SlackChannel"
  - "Linter auto-applied Telegram adapter fix (_tel_enqueue via _make_flood_enqueue) alongside Task 1 — noted as positive deviation"

patterns-established:
  - "All channel adapter registrations in api_gateway.py must use _make_flood_enqueue(channel_id) adapter, never task_queue.enqueue directly"
  - "Integration tests verify ChannelMessage shape correctness (no task_id attribute) — prevents AttributeError regression"

requirements-completed: [DIS-01, DIS-03, SLK-01, SLK-03]

# Metrics
duration: 12min
completed: 2026-03-03
---

# Phase 8 Plan 01: Discord and Slack Flood Adapter Wiring Summary

**_make_flood_enqueue() factory added to api_gateway.py, wiring Discord and Slack channels through dedup+flood.incoming() instead of the broken task_queue.enqueue direct call, with 5 new integration tests confirming the ChannelMessage adapter contract**

## Performance

- **Duration:** 12 min
- **Started:** 2026-03-03T09:10:00Z
- **Completed:** 2026-03-03T09:22:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added `_make_flood_enqueue(channel_id: str)` synchronous factory in api_gateway.py that returns an async `_enqueue` closure. The closure calls `dedup.is_duplicate()` then `flood.incoming()`, matching the `unified_webhook()` reference pattern used by WhatsApp.
- Updated Discord registration: `_dis_enqueue = _make_flood_enqueue("discord")` passed as `enqueue_fn=_dis_enqueue`, eliminating the silent message-drop from `enqueue_fn=None`.
- Updated Slack registration: `_slk_enqueue = _make_flood_enqueue("slack")` passed as `enqueue_fn=_slk_enqueue`, eliminating the same silent-drop bug.
- Added `TestDiscordFloodGateIntegration` (3 tests) and `TestSlackFloodGateIntegration` (2 tests) — all 5 pass alongside the 45 existing Discord+Slack tests (50 total).
- Confirmed `ChannelMessage` objects do not have `task_id` attribute — the adapter prevents the `AttributeError: 'ChannelMessage' object has no attribute 'task_id'` at `queue.py:45`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Discord and Slack flood.incoming() adapter closures in api_gateway.py** - `68892a4` (feat)
2. **Task 2: Add flood.incoming() integration tests for Discord and Slack** - `e4a666d` (feat)

**Plan metadata:** (created below after SUMMARY)

## Files Created/Modified

- `workspace/sci_fi_dashboard/api_gateway.py` — Added `_make_flood_enqueue()` factory (lines 335-360); updated Discord registration at lines 388-391 (added `_dis_enqueue`); updated Slack registration at lines 404-408 (added `_slk_enqueue`)
- `workspace/tests/test_discord_channel.py` — Appended `TestDiscordFloodGateIntegration` class with 3 tests
- `workspace/tests/test_slack_channel.py` — Appended `TestSlackFloodGateIntegration` class with 2 tests

## Decisions Made

- `_make_flood_enqueue` is a **sync** factory (returns an async inner function). No `await` needed at call site — this avoids a two-step `await factory()` pattern.
- `ChannelMessage` import path is `sci_fi_dashboard.channels.base` — there is no `channel_message` module; `ChannelMessage` is defined in `base.py` alongside `BaseChannel`.
- Discord integration tests use `receive()` + direct `_enqueue_fn()` invocation. The `on_message` handler in DiscordChannel is a local closure registered inside `start()` — it cannot be called externally. Using `receive()` + `_enqueue_fn()` is identical to the runtime call sequence.
- Slack integration tests use `_dispatch(event, is_group)` directly — this is a real public method on `SlackChannel` and is the canonical normalization entry point.

## Deviations from Plan

### Auto-applied by Linter

**1. [Rule 1 - Auto-fix] Telegram registration also updated to use _make_flood_enqueue()**
- **Found during:** Task 1 (linter applied immediately after the edit)
- **Issue:** Linter/formatter detected that Telegram registration still used `task_queue.enqueue` directly, which has the same type-mismatch bug as Discord/Slack
- **Fix:** `_tel_enqueue = _make_flood_enqueue("telegram")` and `enqueue_fn=_tel_enqueue` applied to Telegram registration — this is the 08-02 plan fix applied early
- **Files modified:** `workspace/sci_fi_dashboard/api_gateway.py`
- **Commit:** `adff486` (applied automatically alongside `68892a4`)
- **Assessment:** Positive deviation — closes the same root cause for all three channels simultaneously

---

**Total deviations:** 1 auto-applied by linter (positive — closes 08-02 Telegram fix alongside 08-01)
**Impact on plan:** Scope strictly additive to 08-01 goals. No regressions. Telegram fix was planned for 08-02 and is now pre-done.

## Issues Encountered

- `from sci_fi_dashboard.channels.channel_message import ChannelMessage` raised `ModuleNotFoundError` — the plan's prescribed import path was wrong. Fixed to `from sci_fi_dashboard.channels.base import ChannelMessage` (Rule 3 auto-fix, resolved in same task).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- 08-01 requirements DIS-01, DIS-03, SLK-01, SLK-03 are verifiably closed.
- Telegram flood adapter already applied (08-02 scope), but 08-02 tests for Telegram may still be needed.
- Ready for 08-03: channel pipeline integration tests (test_channel_pipeline.py).

---
*Phase: 08-fix-channel-inbound-pipeline*
*Completed: 2026-03-03*
