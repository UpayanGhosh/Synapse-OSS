---
phase: 05-core-channels-telegram-discord-slack
plan: "02"
subsystem: channels
tags: [discord, discord.py, channel-adapter, async, unit-tests]
dependency_graph:
  requires:
    - 03-channel-abstraction-layer (BaseChannel, ChannelMessage, ChannelRegistry)
    - 04-whatsapp-baileys-bridge (pattern reference for channel adapter structure)
  provides:
    - DiscordChannel adapter (discord_channel.py)
    - DIS-01 through DIS-04 unit tests (test_discord_channel.py)
  affects:
    - 05-04 (Discord wiring into api_gateway.py — Wave 2)
tech_stack:
  added:
    - discord.py 2.7.0 (discord.py v2.x async client)
    - audioop-lts 0.2.2 (transitive dependency of discord.py on Python 3.13)
  patterns:
    - await client.start(token) — never client.run() — for uvicorn event-loop compatibility
    - Nested closure event handlers (@client.event) capturing self via closure
    - get_channel() + fetch_channel() cache-with-fallback pattern for outbound sends
    - Privileged intent self-disable: empty content logs CRITICAL and calls stop()
key_files:
  created:
    - workspace/sci_fi_dashboard/channels/discord_channel.py
    - workspace/tests/test_discord_channel.py
  modified: []
decisions:
  - "discord.py 2.7.0 installed into project venv; audioop-lts installed as required transitive dep on Python 3.13"
  - "SIM102 (nested if) auto-fixed in discord_channel.py: combined allowed_channel_ids filter into single if expression"
  - "asyncio import removed from test file (F401); unused ch variable removed from test_server_non_mention_ignored (F841)"
metrics:
  duration: "4 min (238 seconds)"
  completed: "2026-03-02T18:10:32Z"
  tasks_completed: 2
  files_created: 2
  files_modified: 0
requirements_satisfied:
  - DIS-01
  - DIS-02
  - DIS-03
  - DIS-04
---

# Phase 05 Plan 02: DiscordChannel Implementation Summary

**One-liner:** discord.py v2.x async bot adapter with DM+@mention routing, privileged intent self-disable guard, and get_channel()+fetch_channel() fallback for outbound sends.

## What Was Built

### Task 1: `workspace/sci_fi_dashboard/channels/discord_channel.py`

`DiscordChannel(BaseChannel)` — full discord.py v2.x async adapter.

**Key implementation decisions:**

- **File naming:** `discord_channel.py` (never `discord.py`) — prevents Python import system from shadowing the `discord` package itself.
- **Event loop safety:** Uses `await client.start(token)` inside `start()`, which is wrapped in `asyncio.create_task()` by `ChannelRegistry`. Never uses `client.run()` which would block the existing uvicorn event loop.
- **Event handlers:** `on_ready` and `on_message` defined as inner closures before `await client.start()` — closures capture `self` cleanly without needing to store references.
- **Message routing:** DMs (`message.guild is None`) are always dispatched. Server messages dispatched only when bot is @mentioned (`client.user in message.mentions`). Optional `allowed_channel_ids` filter for server messages.
- **Privileged intent guard:** When empty `message.content` arrives for a DM/@mention, this means `MESSAGE_CONTENT` intent is missing from the Discord Developer Portal. Handler logs CRITICAL with remediation steps, sets `_status="failed"`, and schedules `stop()`.
- **Outbound:** `send()` uses `get_channel(int(chat_id))` first (local cache), falling back to `await fetch_channel(int(chat_id))` for channels not in cache. Returns False on `NotFound` or `HTTPException`.
- **No-ops:** `send_typing()` and `mark_read()` are explicit no-ops — Discord bots manage typing inline via `async with message.channel.typing():` and cannot mark messages as read via API.
- **LoginFailure:** Caught in `start()`, sets `_status="failed"` with a clear log message pointing to `channels.discord.token` in `synapse.json`. Does not crash the process.
- **CancelledError:** Caught in `start()`, calls `stop()` for graceful shutdown, then re-raises so `ChannelRegistry` task cancellation propagates correctly.

### Task 2: `workspace/tests/test_discord_channel.py`

25 tests covering all four DIS requirements — all GREEN.

| Requirement | Tests |
|-------------|-------|
| DIS-01 | channel_id, LoginFailure handling, initial status |
| DIS-02 | receive() normalization, DM dispatch, @mention dispatch, server non-mention ignored, empty-content guard |
| DIS-03 | send() cache+fallback, not-found, HTTP error, send_typing no-op, mark_read no-op |
| DIS-04 | health_check shape (stopped/running/closed/no-user), constructor storage |

Module-level `skipif` guard (`DIS_AVAILABLE`) mirrors `test_whatsapp_channel.py` pattern — tests skip cleanly if `discord_channel.py` is absent.

## Verification Results

```
pytest tests/test_discord_channel.py -v
25 passed in 1.17s

ruff check workspace/sci_fi_dashboard/channels/discord_channel.py workspace/tests/test_discord_channel.py
All checks passed!

python -c "from sci_fi_dashboard.channels.discord_channel import DiscordChannel; ch = DiscordChannel(token='fake'); print('channel_id:', ch.channel_id)"
channel_id: discord
```

File confirmed named `discord_channel.py` (not `discord.py`). DiscordChannel is NOT wired into `api_gateway.py` — that is Wave 2 (plan 05-04).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] SIM102 ruff violation in discord_channel.py**
- **Found during:** Task 1 ruff check
- **Issue:** Nested `if` statements for allowed_channel_ids filter flagged by ruff SIM102
- **Fix:** Combined into single `if not is_dm and self._allowed_channel_ids and message.channel.id not in self._allowed_channel_ids:` expression
- **Files modified:** `workspace/sci_fi_dashboard/channels/discord_channel.py`
- **Commit:** 4214101

**2. [Rule 1 - Bug] F401 + F841 ruff violations in test file**
- **Found during:** Task 2 ruff check
- **Issue:** `asyncio` imported but unused (F401); `ch` variable assigned but unused in `test_server_non_mention_ignored` (F841)
- **Fix:** Removed `import asyncio`; removed `ch = DiscordChannel(...)` assignment in the routing logic test
- **Files modified:** `workspace/tests/test_discord_channel.py`
- **Commit:** f10bcfa

**3. [Rule 3 - Blocking] discord.py not installed**
- **Found during:** Task 1 pre-implementation check
- **Issue:** `import discord` would fail — discord.py not in venv
- **Fix:** `pip install "discord.py>=2.0"` → installed discord.py 2.7.0 + audioop-lts 0.2.2
- **Files modified:** none (package install only)
- **Impact:** requirements.txt should be updated in a later phase if needed

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | 4214101 | feat(05-02): implement DiscordChannel in channels/discord_channel.py |
| Task 2 | f10bcfa | feat(05-02): add test_discord_channel.py covering DIS-01 through DIS-04 |

## Self-Check: PASSED

- [x] `workspace/sci_fi_dashboard/channels/discord_channel.py` exists
- [x] `workspace/tests/test_discord_channel.py` exists
- [x] Commit 4214101 exists in git log
- [x] Commit f10bcfa exists in git log
- [x] 25/25 tests GREEN
- [x] Ruff clean on both files
- [x] DiscordChannel NOT in `__init__.py` exports (Wave 2 wiring is plan 05-04)
