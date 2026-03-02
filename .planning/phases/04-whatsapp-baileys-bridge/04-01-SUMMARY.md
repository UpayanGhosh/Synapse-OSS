---
phase: 04-whatsapp-baileys-bridge
plan: 01
subsystem: testing
tags: [pytest, tdd, whatsapp, baileys, asyncio, subprocess-mock]

# Dependency graph
requires:
  - phase: 03-channel-abstraction-layer
    provides: BaseChannel ABC, ChannelRegistry, ChannelMessage, StubChannel — whatsapp.py will subclass BaseChannel
provides:
  - 8 RED tests covering WA-01 through WA-08 in test_whatsapp_channel.py
  - WA_AVAILABLE guard pattern (importlib.util.find_spec) that auto-transitions to GREEN when whatsapp.py ships
  - AsyncMock subprocess mock helpers (_make_mock_process) for supervisor loop tests
affects: 04-03-PLAN (implements WhatsAppChannel to turn these tests GREEN)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - importlib.util.find_spec guard + pytestmark.skipif for RED->GREEN TDD transitions without conftest changes
    - _make_mock_process() factory for asyncio subprocess simulation (crash/running variants)
    - monkeypatch.setattr(shutil, "which", ...) for Node.js detection tests

key-files:
  created:
    - workspace/tests/test_whatsapp_channel.py
  modified: []

key-decisions:
  - "WA-01/03/04/05/07 are file-system checks placed outside the WA_AVAILABLE guard — they SKIP when whatsapp.py missing but naturally FAIL when file-system artifacts (baileys-bridge/) also missing"
  - "pytestmark = pytest.mark.skipif(not WA_AVAILABLE) applied module-wide — all 8 tests SKIP until whatsapp.py exists; mirrors test_channels.py and test_llm_router.py pattern"
  - "_make_mock_process() factory supports two modes: returncode=None (running forever) and returncode=N (exits immediately for crash simulation) — reused by WA-02 and WA-06"
  - "monkeypatch.setattr(shutil, 'which', lambda name: None) patches shutil module attribute directly — more robust than patching asyncio.create_subprocess_exec for Node.js presence test"

patterns-established:
  - "AsyncMock supervisor test: create_task(channel.start()) → yield asyncio.sleep(0) multiple times → cancel → check call_count"
  - "File-system endpoint check: read index.js src as string, assert 'app.{verb}(\"{path}\"' in src"

requirements-completed: [WA-01, WA-02, WA-03, WA-04, WA-05, WA-06, WA-07, WA-08]

# Metrics
duration: 8min
completed: 2026-03-02
---

# Phase 4 Plan 01: WhatsApp Baileys Bridge Test Scaffold Summary

**8 RED TDD tests covering all WA requirements, with WA_AVAILABLE import guard and AsyncMock subprocess helpers — all SKIP until Phase 04-03 ships WhatsAppChannel**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-02T16:29:21Z
- **Completed:** 2026-03-02T16:37:33Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Created `workspace/tests/test_whatsapp_channel.py` with 8 test functions, one per WA requirement
- All 8 tests SKIP cleanly (correct RED state) with `pytestmark` guard — no collection errors
- Existing 162-test suite unaffected (162 passed, 8 skipped, 4 xfailed in full run)
- AsyncMock subprocess helpers support both crash (returncode=1) and running (returncode=None) scenarios

## Task Commits

Each task was committed atomically:

1. **Task 1: Write RED tests for all 8 WA requirements** - `8a159fc` (test)

**Plan metadata:** _(to be added in final commit)_

_Note: TDD tasks may have multiple commits (test → feat → refactor)_

## Files Created/Modified

- `workspace/tests/test_whatsapp_channel.py` — 8 tests for WA-01 through WA-08; all SKIP until Phase 04-03; includes _make_mock_process() AsyncMock factory for subprocess simulation

## Decisions Made

- **WA_AVAILABLE guard as pytestmark:** Module-level `pytestmark = pytest.mark.skipif(not WA_AVAILABLE, ...)` applied to all 8 tests. This means file-system checks (WA-01/03/04/05/07) also skip when `whatsapp.py` is absent, keeping the RED phase clean — they naturally fail once the module exists but bridge files don't yet.
- **_make_mock_process() factory:** Two-mode helper: `returncode_after_start=None` for long-running process (WA-02), `returncode_after_start=1` for crash simulation (WA-06). Avoids duplicating mock setup across tests.
- **shutil patching for Node.js test (WA-08):** `monkeypatch.setattr(shutil, "which", lambda name: None)` patches the module object directly, which is more reliable than `monkeypatch.setattr("shutil.which", ...)` when the target module imports shutil at top level.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Test scaffold complete and passing (SKIP state) — ready for Phase 04-02 to ship `baileys-bridge/` files
- WA-01/03/04/05/07 (file-system checks) will transition from SKIP to FAIL once `whatsapp.py` exists but before bridge files arrive — expected behavior
- WA-02/06/08 will FAIL immediately after `whatsapp.py` ships (before implementation is correct) — confirms RED->GREEN TDD flow
- Phase 04-03 (WhatsAppChannel implementation) will turn all 8 tests GREEN

---
*Phase: 04-whatsapp-baileys-bridge*
*Completed: 2026-03-02*
