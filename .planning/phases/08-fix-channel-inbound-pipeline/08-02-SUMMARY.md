---
phase: 08-fix-channel-inbound-pipeline
plan: "02"
subsystem: channel-pipeline
tags: [telegram, flood-gate, enqueue-fn, type-boundary, inbound-pipeline]
dependency_graph:
  requires: [07-04, 08-01]
  provides: [TEL-01, TEL-03]
  affects: [workspace/sci_fi_dashboard/api_gateway.py, workspace/tests/test_telegram_channel.py]
tech_stack:
  added: []
  patterns:
    - _make_flood_enqueue factory adapter: routes ChannelMessage → flood.incoming() for all channels
    - Moved factory before first channel block: ensures availability at module init time
key_files:
  modified:
    - workspace/sci_fi_dashboard/api_gateway.py
    - workspace/tests/test_telegram_channel.py
decisions:
  - "Factory placement: _make_flood_enqueue moved before Telegram block — Python top-to-bottom execution requires factory defined before first call site; Plan 08-01 had placed it after the Telegram block causing NameError at startup if telegram token was configured"
  - "Test uses _make_mock_update() not ChannelMessage directly — _dispatch() takes PTB Update objects and converts them internally; plan spec's ChannelMessage-to-_dispatch pattern was incorrect"
  - "Import path: sci_fi_dashboard.channels.base.ChannelMessage (not .channel_message) — base.py is the actual location; corrected from plan spec"
requirements_completed: [TEL-01, TEL-03]
metrics:
  duration_minutes: 4
  completed_date: "2026-03-03"
  tasks_completed: 2
  files_modified: 2
---

# Phase 08 Plan 02: Fix Telegram Inbound Pipeline Summary

**One-liner:** Fixed Telegram channel to route ChannelMessage through flood.incoming() adapter (_tel_enqueue = _make_flood_enqueue("telegram")), replacing broken task_queue.enqueue injection; also corrected factory placement to before the Telegram block to prevent NameError at startup.

## What Was Built

### Task 1: Replace Telegram enqueue_fn registration with flood.incoming() adapter

**File:** `workspace/sci_fi_dashboard/api_gateway.py`

**Problem discovered:** Plan 08-01 had placed `_make_flood_enqueue` AFTER the Telegram registration block (line 353 vs Telegram block at line 335-351). Since Python executes module-level code top-to-bottom, the factory was not yet defined when the Telegram block tried to call it — this would cause a NameError at startup when a telegram token is configured.

**Fix applied:** Moved `_make_flood_enqueue` factory to before the Telegram block, then added the correct Telegram registration pattern.

**Before (line 340):**
```python
channel_registry.register(TelegramChannel(token=_tg_token, enqueue_fn=task_queue.enqueue))
```

**After (lines 363-370):**
```python
_tg_token = _ch_cfg.get("telegram", {}).get("token", "").strip()
if _tg_token:
    try:
        from channels.telegram import TelegramChannel  # noqa: E402

        _tel_enqueue = _make_flood_enqueue("telegram")
        channel_registry.register(TelegramChannel(token=_tg_token, enqueue_fn=_tel_enqueue))
```

**Final registration state (all three channels):**
```
Line 369: enqueue_fn=_tel_enqueue   (Telegram)
Line 390: enqueue_fn=_dis_enqueue   (Discord)
Line 412: enqueue_fn=_slk_enqueue   (Slack)
```
No channel registration passes `task_queue.enqueue` directly.

### Task 2: Add flood.incoming() adapter integration tests

**File:** `workspace/tests/test_telegram_channel.py`

New class `TestTelegramFloodGateIntegration` with 3 tests:

1. **test_dispatch_routes_via_flood_adapter** — verifies `_dispatch()` routes through the adapter with correct shape (channel_id, text, chat_id, sender_name)
2. **test_dispatch_no_task_id_attribute_error** — asserts `ChannelMessage` has no `task_id` attribute, proving that the old `task_queue.enqueue` wiring would crash with `AttributeError`
3. **test_dispatch_no_enqueue_fn_logs_warning** — verifies that `enqueue_fn=None` drops message gracefully (no crash)

**Note:** Tests use `_make_mock_update()` (PTB Update mock) not `ChannelMessage` directly — `_dispatch()` expects a PTB `Update` object and converts it internally. The plan spec's approach of passing `ChannelMessage` to `_dispatch()` was corrected.

## Test Results

```
25 passed in 1.19s

- 22 pre-existing tests: all PASS
- 3 new TestTelegramFloodGateIntegration tests: all PASS
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Factory placement: _make_flood_enqueue defined after its first call site**
- **Found during:** Task 1
- **Issue:** Plan 08-01 had placed the factory function at line 353, after the Telegram registration block (lines 335-351). Python module-level code executes top-to-bottom; calling `_make_flood_enqueue("telegram")` on line 340 when the function is defined at line 353 would raise `NameError` at startup when a telegram token is configured.
- **Fix:** Removed the old Telegram registration block (which had both the broken wiring and the factory definition after), then added the factory first, followed by a corrected Telegram registration block.
- **Files modified:** workspace/sci_fi_dashboard/api_gateway.py
- **Commit:** adff486

**2. [Rule 1 - Bug] Test uses _dispatch(Update) not _dispatch(ChannelMessage)**
- **Found during:** Task 2
- **Issue:** Plan spec showed `await ch._dispatch(channel_msg)` where `channel_msg` is a `ChannelMessage`. The actual `_dispatch()` signature is `async def _dispatch(self, update: Update) -> None` — it takes a PTB Update object, converts it to ChannelMessage internally, then calls `enqueue_fn(channel_msg)`. Passing a ChannelMessage directly would crash with `AttributeError: 'ChannelMessage' object has no attribute 'message'`.
- **Fix:** Tests use `_make_mock_update()` helper (already in the test file) to build PTB Update mocks, consistent with all existing test patterns.
- **Files modified:** workspace/tests/test_telegram_channel.py
- **Commit:** 58326e1

**3. [Rule 3 - Blocking] Wrong ChannelMessage import path in plan spec**
- **Found during:** Task 2
- **Issue:** Plan spec referenced `from sci_fi_dashboard.channels.channel_message import ChannelMessage` — no such module exists. The class is in `sci_fi_dashboard.channels.base`.
- **Fix:** Used correct import `from sci_fi_dashboard.channels.base import ChannelMessage` (though this import was ultimately not needed since tests use mock Update objects instead).
- **Files modified:** workspace/tests/test_telegram_channel.py
- **Commit:** 58326e1

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | adff486 | feat(08-02): fix Telegram enqueue_fn registration to use flood.incoming() adapter |
| Task 2 | 58326e1 | test(08-02): add TestTelegramFloodGateIntegration — flood adapter integration tests |

## Requirements Closed

- **TEL-01:** Telegram inbound dispatch routes through flood.incoming() adapter — no AttributeError on task_id — CLOSED
- **TEL-03:** Outbound send/send_typing reachable after inbound fix — confirmed by 22 existing passing tests — CLOSED

## Self-Check: PASSED

- FOUND: workspace/sci_fi_dashboard/api_gateway.py
- FOUND: workspace/tests/test_telegram_channel.py
- FOUND: .planning/phases/08-fix-channel-inbound-pipeline/08-02-SUMMARY.md
- FOUND commit: adff486 (Task 1)
- FOUND commit: 58326e1 (Task 2)
