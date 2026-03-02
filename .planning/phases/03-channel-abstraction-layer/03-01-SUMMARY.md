---
phase: 03-channel-abstraction-layer
plan: "01"
subsystem: api
tags: [asyncio, abc, dataclass, channels, adapter-pattern]

# Dependency graph
requires: []
provides:
  - "BaseChannel ABC with abstract channel_id property and receive/send/send_typing/mark_read/health_check methods"
  - "ChannelMessage dataclass with field(default_factory=dict) for raw (no shared mutable default)"
  - "ChannelRegistry managing channel lifecycle via asyncio.create_task() — never asyncio.run()"
  - "StubChannel concrete implementation for testing; sent_messages records outbound (chat_id, text) pairs"
  - "channels package __init__.py exporting all four public names"
affects:
  - "03-channel-abstraction-layer (plans 02-04 all subclass BaseChannel or use ChannelRegistry)"
  - "04-whatsapp-channel"
  - "05-telegram-channel"
  - "06-discord-channel"
  - "07-slack-channel"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ABC with @property @abstractmethod for channel_id — property first, abstractmethod second"
    - "asyncio.create_task() for non-blocking channel start — matches api_gateway.py lifespan pattern"
    - "field(default_factory=dict) for mutable dataclass defaults — prevents shared-dict bug"
    - "ChannelRegistry as instance (not singleton module-level) — injectable, testable"

key-files:
  created:
    - workspace/sci_fi_dashboard/channels/__init__.py
    - workspace/sci_fi_dashboard/channels/base.py
    - workspace/sci_fi_dashboard/channels/registry.py
    - workspace/sci_fi_dashboard/channels/stub.py
  modified: []

key-decisions:
  - "asyncio.create_task() wraps channel.start() in start_all() — NEVER asyncio.run() — uvicorn already owns the event loop; calling asyncio.run() inside an existing loop raises RuntimeError"
  - "ChannelRegistry is an instance (not a module-level singleton) — allows tests to create independent registries without reset"
  - "StubChannel.start() returns immediately — asyncio task completes in next event-loop iteration; callers needing to observe _started must await asyncio.sleep(0) after start_all()"
  - "stop_all() cancels tasks first, then gathers with return_exceptions=True, then calls stop() on each channel — mirrors lifespan shutdown pattern in api_gateway.py"

patterns-established:
  - "Channel adapter pattern: subclass BaseChannel, implement all @abstractmethod members, register with ChannelRegistry"
  - "Lifecycle pattern: registry.register() at startup, await registry.start_all() in lifespan, await registry.stop_all() in lifespan teardown"
  - "Test pattern: StubChannel('id') for unit tests; inspect stub.sent_messages for outbound verification"

requirements-completed: [CHAN-01, CHAN-02, CHAN-03, CHAN-06]

# Metrics
duration: 6min
completed: 2026-03-02
---

# Phase 3 Plan 01: Channel Abstraction Layer — Base Primitives Summary

**Four-file channels subpackage: BaseChannel ABC + ChannelMessage dataclass + ChannelRegistry with asyncio.create_task lifecycle + StubChannel concrete implementation**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-02T11:43:45Z
- **Completed:** 2026-03-02T11:50:07Z
- **Tasks:** 3
- **Files modified:** 4 created, 0 modified

## Accomplishments

- Created `ChannelMessage` dataclass with all required fields; `raw` uses `field(default_factory=dict)` — no shared mutable default bug
- Created `BaseChannel` ABC with abstract `channel_id` property and five abstract async methods; non-abstract `start`/`stop` lifecycle hooks default to no-ops
- Created `ChannelRegistry` that wraps each channel's `start()` in `asyncio.create_task()` — prevents `RuntimeError` from `asyncio.run()` inside uvicorn's event loop
- Created `StubChannel` that fully implements `BaseChannel`; records `(chat_id, text)` tuples in `sent_messages` for test assertions
- Created `channels/__init__.py` exposing all four public names via `__all__`

## Task Commits

Each task was committed atomically:

1. **Task 1: Create channels/base.py — ChannelMessage and BaseChannel ABC** - `d1cfcc5` (feat)
2. **Task 2: Create channels/registry.py — ChannelRegistry singleton** - `dd9d3f1` (feat)
3. **Task 3: Create channels/stub.py + channels/__init__.py** - `b237e5a` (feat)

## Files Created/Modified

- `workspace/sci_fi_dashboard/channels/base.py` — ChannelMessage dataclass + BaseChannel ABC with all abstract methods and lifecycle hooks
- `workspace/sci_fi_dashboard/channels/registry.py` — ChannelRegistry: register/get/list_ids + start_all/stop_all lifecycle management
- `workspace/sci_fi_dashboard/channels/stub.py` — StubChannel: full concrete implementation for testing; records sent messages
- `workspace/sci_fi_dashboard/channels/__init__.py` — package root re-exporting all four public names; `__all__` defined

## Decisions Made

- `asyncio.create_task()` is the only way to launch channels from `start_all()` — `asyncio.run()` raises `RuntimeError` inside uvicorn's running event loop. This mirrors the existing `gentle_worker_loop` pattern in `api_gateway.py`.
- `ChannelRegistry` is an instance, not a module-level singleton — tests can create independent registries, no global state to reset between tests.
- `StubChannel.start()` returns immediately — the asyncio task completes in the next event-loop iteration. Any caller asserting on `_started` after `start_all()` must yield with `await asyncio.sleep(0)`.
- `stop_all()` follows the exact lifespan shutdown pattern from `api_gateway.py`: cancel tasks → gather with `return_exceptions=True` → call `stop()` on each adapter.

## Deviations from Plan

None — plan executed exactly as written.

**Note:** The plan's verification script required `await asyncio.sleep(0)` after `start_all()` to observe `_started=True` — this is expected asyncio task scheduling behavior, not a code bug. The production code (using `create_task`) is correct; tests that inspect task side-effects must yield once.

## Issues Encountered

- The pre-existing `test_concurrent_writes` performance test fails on this Windows machine (~51s vs <10s threshold) due to SQLite concurrent write latency — pre-existing, unrelated to this plan's changes (confirmed by running the test on the unmodified codebase).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `BaseChannel`, `ChannelMessage`, `ChannelRegistry`, `StubChannel` are importable from `sci_fi_dashboard.channels`
- Plan 02 (TDD test scaffold) can reference `StubChannel` for RED-phase tests
- Plans 03-04 (WhatsApp/Telegram adapters) subclass `BaseChannel` and register with `ChannelRegistry`
- No blockers

## Self-Check: PASSED

- FOUND: workspace/sci_fi_dashboard/channels/base.py
- FOUND: workspace/sci_fi_dashboard/channels/registry.py
- FOUND: workspace/sci_fi_dashboard/channels/stub.py
- FOUND: workspace/sci_fi_dashboard/channels/__init__.py
- FOUND: .planning/phases/03-channel-abstraction-layer/03-01-SUMMARY.md
- FOUND commit d1cfcc5: feat(03-01): add ChannelMessage dataclass and BaseChannel ABC
- FOUND commit dd9d3f1: feat(03-01): add ChannelRegistry with asyncio.create_task lifecycle
- FOUND commit b237e5a: feat(03-01): add StubChannel and channels package __init__ exports

---
*Phase: 03-channel-abstraction-layer*
*Completed: 2026-03-02*
