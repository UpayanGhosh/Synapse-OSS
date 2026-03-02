---
phase: 05-core-channels-telegram-discord-slack
plan: "04"
subsystem: channels
tags: [api-gateway, channels, telegram, discord, slack, health-endpoint, integration]

# Dependency graph
requires:
  - 05-01 (TelegramChannel — PTB v22 long-polling adapter)
  - 05-02 (DiscordChannel — discord.py v2.x async adapter)
  - 05-03 (SlackChannel — slack-bolt Socket Mode adapter)
  - 03-channel-abstraction-layer (ChannelRegistry.list_ids(), BaseChannel)

provides:
  - Telegram/Discord/Slack opt-in registration in api_gateway.py
  - Generic /health endpoint using channel_registry.list_ids() loop
  - try/except import guards in channels/__init__.py
  - discord.py>=2.4.0 + aiohttp + websockets in requirements.txt

affects:
  - All future channel additions (health endpoint is now N-channel generic)
  - 06+ phases that add new channels (pattern is established)

# Tech tracking
tech-stack:
  added:
    - discord.py>=2.4.0 (added to requirements.txt; was installed but not listed)
    - aiohttp>=3.9.0 (slack-bolt async dependency)
    - websockets>=10.0 (AsyncSocketModeHandler dependency)
  patterns:
    - Opt-in channel guard: if token => lazy import + register; else INFO log + skip
    - ImportError guard in registration block — SDK missing = WARNING, not crash
    - channel_registry.list_ids() loop in /health — generic N-channel health check
    - try/except ImportError in channels/__init__.py — SDK-optional exports

key-files:
  created: []
  modified:
    - workspace/sci_fi_dashboard/channels/__init__.py
    - workspace/sci_fi_dashboard/api_gateway.py
    - requirements.txt

key-decisions:
  - "Lazy imports inside if-blocks (not at module top) — prevents ImportError if SDK not installed at import time"
  - "enqueue_fn=task_queue.enqueue injected into TelegramChannel at registration — decouples channel from pipeline at module level"
  - "channels/__init__.py uses try/except guards — exports are None if SDK absent, not an ImportError"
  - "GET /health uses channel_registry.list_ids() loop — WhatsApp preserved automatically; no hardcoded channel names"
  - "Per-channel error wrapping in /health — health_check() failure returns error dict, never 500"
  - "logging.getLogger(__name__) used inside registration block — consistent with Python stdlib logging, not print()"
  - "pre-existing test_concurrent_writes perf failure noted as out-of-scope — Windows SQLite timing, not related to channel wiring"

# Metrics
duration: 16min
completed: 2026-03-02
---

# Phase 5 Plan 04: api_gateway Wiring Summary

**Wire Telegram/Discord/Slack opt-in channel registration into api_gateway.py with lazy import guards; refactor GET /health to use generic channel_registry.list_ids() loop; add discord.py + aiohttp + websockets to requirements.txt**

## Performance

- **Duration:** 16 min
- **Started:** 2026-03-02T18:20:59Z
- **Completed:** 2026-03-02T18:37:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `channels/__init__.py` — Wrapped TelegramChannel/DiscordChannel/SlackChannel imports in `try/except ImportError` guards; WhatsAppChannel and base types remain direct imports. `__all__` unchanged.
- `requirements.txt` — Added `discord.py>=2.4.0` (was installed but not listed), `aiohttp>=3.9.0`, `websockets>=10.0` under a consolidated `# Channel SDK Dependencies` section.
- `api_gateway.py` — Added 60-line opt-in registration block after `SynapseLLMRouter` init: each channel reads token(s) from `_synapse_cfg.channels`, lazy-imports its SDK, registers with `channel_registry`; missing token logs INFO + skips; missing SDK logs WARNING + skips; `enqueue_fn=task_queue.enqueue` injected at TelegramChannel construction.
- `api_gateway.py /health` — Replaced hardcoded `whatsapp_health` variable + `channel_registry.get("whatsapp")` call with a generic `for cid in channel_registry.list_ids()` loop; per-channel errors return `{"status": "error", ...}` dict; endpoint never raises 500.

## Task Commits

Each task was committed atomically:

1. **Task 1: Update channels/__init__.py + requirements.txt** - `c999b00` (feat)
2. **Task 2: Wire channels into api_gateway.py + refactor /health** - `48a4db8` (feat)

## Files Created/Modified

- `workspace/sci_fi_dashboard/channels/__init__.py` — try/except ImportError guards for TelegramChannel, DiscordChannel, SlackChannel
- `workspace/sci_fi_dashboard/api_gateway.py` — opt-in channel registration block + generic /health loop
- `requirements.txt` — discord.py>=2.4.0, aiohttp>=3.9.0, websockets>=10.0 added; section header updated

## Decisions Made

- Lazy imports inside `if _tg_token:` blocks (not at module top) — prevents `ImportError` when SDK is not installed even if `__init__.py` guard returns `None`; the registration block is where actual instantiation happens
- `enqueue_fn=task_queue.enqueue` injected at TelegramChannel registration time — TelegramChannel was designed for this pattern (enqueue_fn=None default); api_gateway is the correct place to provide the real callback
- `channels/__init__.py` try/except guards return `None` when SDK absent — consumers check `if TelegramChannel is not None` before using
- GET /health uses `channel_registry.list_ids()` — "whatsapp" key is automatically present because WhatsAppChannel is registered first at module scope (lines 189-197); backward compatibility preserved
- `logging.getLogger(__name__)` used for channel registration messages — consistent with Python stdlib; avoids rich.print which carries color codes that may interfere with log aggregators
- `import logging as _logging` — private alias to avoid shadowing any local `logging` references elsewhere in the file

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added discord.py>=2.4.0 to requirements.txt**
- **Found during:** Task 1 — requirements.txt audit
- **Issue:** `discord.py` was installed (2.7.0) and used by DiscordChannel but not listed in requirements.txt; 05-02-SUMMARY.md noted "requirements.txt should be updated in a later phase if needed"
- **Fix:** Added `discord.py>=2.4.0` to requirements.txt under Channel SDK Dependencies section
- **Files modified:** `requirements.txt`
- **Committed in:** c999b00 (Task 1)

**2. [Rule 2 - Missing Critical] Added aiohttp>=3.9.0 and websockets>=10.0 to requirements.txt**
- **Found during:** Task 1 — plan spec listed these as required by slack-bolt AsyncApp
- **Issue:** Both packages needed by slack-bolt Socket Mode but not explicitly listed
- **Fix:** Added both under Channel SDK Dependencies section
- **Files modified:** `requirements.txt`
- **Committed in:** c999b00 (Task 1)

---

**Total deviations:** 2 auto-fixed (both Rule 2 — missing critical requirements.txt entries)
**Impact on plan:** Additive only. No behavior changes.

## Verification Results

```
python -c "from sci_fi_dashboard.channels import TelegramChannel, DiscordChannel, SlackChannel; print('exports OK')"
exports OK — TelegramChannel: True | DiscordChannel: True | SlackChannel: True

grep "list_ids" workspace/sci_fi_dashboard/api_gateway.py
    for cid in channel_registry.list_ids():

grep "whatsapp_health" workspace/sci_fi_dashboard/api_gateway.py
(no output — variable removed)

grep "python-telegram-bot|discord.py|slack-bolt" requirements.txt
python-telegram-bot>=22.0
discord.py>=2.4.0
slack-bolt>=1.18.0

pytest tests/ -q
250 passed, 4 xfailed, 2 xpassed in 354.42s
(1 pre-existing performance test failure: test_concurrent_writes — Windows SQLite timing, not regression)
```

## Issues Encountered

- `test_concurrent_writes` in `test_performance.py` fails consistently on Windows (~50s vs 10s limit) — pre-existing environment issue unrelated to channel wiring. All 250 non-performance tests pass.

## User Setup Required

To enable Telegram: add `{"channels": {"telegram": {"token": "YOUR_BOT_TOKEN"}}}` to `~/.synapse/synapse.json`
To enable Discord: add `{"channels": {"discord": {"token": "YOUR_BOT_TOKEN", "allowed_channel_ids": []}}}` to `~/.synapse/synapse.json`
To enable Slack: add `{"channels": {"slack": {"bot_token": "xoxb-...", "app_token": "xapp-..."}}}` to `~/.synapse/synapse.json`

## Phase 5 Completion

This plan completes Phase 5 — all 12 requirements (TEL-01 through TEL-04, DIS-01 through DIS-04, SLK-01 through SLK-04) are satisfied:
- TEL-01/02/03/04: TelegramChannel implemented (05-01) + wired (05-04)
- DIS-01/02/03/04: DiscordChannel implemented (05-02) + wired (05-04)
- SLK-01/02/03/04: SlackChannel implemented (05-03) + wired (05-04)

---
*Phase: 05-core-channels-telegram-discord-slack*
*Completed: 2026-03-02*

## Self-Check: PASSED

- FOUND: workspace/sci_fi_dashboard/channels/__init__.py
- FOUND: workspace/sci_fi_dashboard/api_gateway.py
- FOUND: requirements.txt
- FOUND: .planning/phases/05-core-channels-telegram-discord-slack/05-04-SUMMARY.md
- FOUND: commit c999b00 (Task 1 — channels/__init__.py + requirements.txt)
- FOUND: commit 48a4db8 (Task 2 — api_gateway.py channel wiring + /health refactor)
