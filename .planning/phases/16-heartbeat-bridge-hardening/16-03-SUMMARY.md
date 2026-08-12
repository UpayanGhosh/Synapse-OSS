# Phase 16 Plan 03 Task 2 — Summary

## Status: DONE

## What was done

Three surgical edits to `workspace/sci_fi_dashboard/channels/whatsapp.py`:

### Edit 1 — `__init__` new slots (line 110-111)
- Added `self._restart_in_progress: asyncio.Event = asyncio.Event()`
- Added `self._bridge_health_poller: Any = None`
- Also added `from typing import Any` import (was missing)
- Fixes critical C1 issue: production `WhatsAppChannel` now has the Event that
  Task 1 poller code assumed existed (tests mocked it in, production didn't have it)

### Edit 2 — `_restart_bridge` G2 race guard (lines 249-271)
- Guard at entry: `if self._restart_in_progress.is_set(): return`
- Set flag before work, clear in `finally` block
- Prevents Phase 14 watchdog + Phase 16 poller from double-restarting the bridge
  simultaneously — second caller no-ops, first completes

### Edit 3 — `get_status` bridge_health surface (lines 356-360)
- Added `base["bridge_health"]` key after `stop_reconnect`
- Returns `self._bridge_health_poller.last_health` when poller is wired (Plan 04)
- Returns `{}` when poller is None (pre-Plan-04, safe default)

## Test Results

| Suite | Result |
|---|---|
| `test_bridge_health_poller.py` | 7/7 PASSED |
| `test_supervisor_watchdog.py` | 15/15 PASSED |
| `test_channel_whatsapp_extended.py` | 22/22 PASSED |
| **Total** | **44/44 PASSED** |

Zero regression. All Phase 14 + Phase 15 tests remain GREEN.

## Grep Proofs

- `_restart_in_progress: asyncio.Event` — 1 match (line 110, `__init__`)
- `_restart_in_progress` total occurrences — 5 (init + guard + set + clear + logger)
- `bridge_health` total occurrences — 9 (get_status if/else + poller access)
- `if self._restart_in_progress.is_set()` — 1 match (line 253, `_restart_bridge`)

## Lint

- `ruff check` — clean (I001 import sort auto-fixed)
- `black --check` — clean (reformatted once after ruff reorder)

## Commit

`39f9b16` on branch `develop`

## Plan 04 Unblocked

`_bridge_health_poller` slot exists. Plan 04 lifespan wiring can now do:
```python
channel._bridge_health_poller = BridgeHealthPoller(channel=channel, ...)
```
without `setattr` hacks. `_restart_in_progress` Event is live on the real
channel so poller's `_channel._restart_in_progress.is_set()` guard works in
production without AttributeError.
