---
phase: 09-image-generation
plan: "03"
subsystem: api
tags: [image-generation, background-task, fastapi-static-files, chat-pipeline, vault-safety]

# Dependency graph
requires:
  - phase: 09-image-generation/09-01
    provides: ImageGenEngine with generate() → bytes | None, SynapseConfig.image_gen
  - phase: 09-image-generation/09-02
    provides: IMAGE fifth classification label in traffic cop, IMAGE routing branch placeholder
provides:
  - Full IMAGE BackgroundTask dispatch in chat_pipeline.py (ack text + async image delivery)
  - Vault hemisphere block in IMAGE branch (no API calls in spicy sessions)
  - enabled check in IMAGE branch (soft decline when image_gen.enabled=false)
  - _generate_and_send_image() async helper (ImageGenEngine + save_media_buffer + send_media)
  - StaticFiles mount at /media/image_gen_outbound for PNG serving
  - 10-test suite covering engine, pipeline routing, Vault block, and delivery
affects:
  - phase-10 (dashboard SSE events for image_gen role can now fire in real pipeline)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "IMAGE BackgroundTask pattern: enabled check → Vault block → add_task → ack return (same as auto-continue)"
    - "save_media_buffer wrapped in asyncio.to_thread() to prevent event loop blocking on file I/O"
    - "StaticFiles mount per-subdirectory pattern: /media/image_gen_outbound mirrors /media/tts_outbound"
    - "Test stub strategy: stub sci_fi_dashboard._deps at sys.modules level before import to avoid circular import + heavy transitive deps"
    - "STRATEGY_TO_ROLE must be patched to {} in pipeline routing tests to ensure traffic cop is called"

key-files:
  created:
    - workspace/tests/test_image_gen.py
  modified:
    - workspace/sci_fi_dashboard/chat_pipeline.py
    - workspace/sci_fi_dashboard/api_gateway.py

key-decisions:
  - "Vault block in IMAGE branch is defense-in-depth: spicy sessions are already caught at outer vault routing (line 622) before reaching IMAGE — IMAGE Vault block guards any future bypass path"
  - "save_media_buffer() wrapped in asyncio.to_thread() because it performs synchronous file I/O (os.open, os.replace, os.chmod, directory iteration) that blocks the event loop"
  - "channel_id hardcoded to 'whatsapp' inside _generate_and_send_image() — persona_chat() has no channel_id in scope; matches continue_conversation() default in pipeline_helpers.py"
  - "Test stub strategy: stub sci_fi_dashboard._deps at sys.modules level to break circular import chain and avoid pyarrow/lancedb/flashrank/torch being required in test env"

patterns-established:
  - "BackgroundTask dispatch pattern: if background_tasks: add_task(...) else: asyncio.create_task(...) — same as auto-continue in pipeline"
  - "Per-subdirectory StaticFiles mount pattern established in Phase 8 (TTS) and followed here (image gen)"

requirements-completed:
  - IMG-01
  - IMG-04
  - IMG-05

# Metrics
duration: 20min
completed: "2026-04-09"
---

# Phase 9 Plan 03: Image Pipeline Integration Summary

**BackgroundTask image delivery with Vault safety enforcement, /media/image_gen_outbound StaticFiles mount, and 10 passing tests covering engine, pipeline routing, and async delivery**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-04-09T19:03:00Z
- **Completed:** 2026-04-09T19:23:00Z
- **Tasks:** 2
- **Files modified:** 3 (chat_pipeline.py, api_gateway.py, test_image_gen.py created)

## Accomplishments

- Replaced placeholder IMAGE branch with full BackgroundTask dispatch: enabled check → Vault block → `_generate_and_send_image` async helper → immediate ack reply returned
- Added StaticFiles mount `/media/image_gen_outbound` to api_gateway.py (mirrors Phase 8 TTS pattern, directory auto-created at startup)
- 10 passing tests: 5 engine unit tests + 3 pipeline routing tests + 2 background delivery tests (100% pass rate)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire IMAGE BackgroundTask dispatch with Vault block in chat_pipeline.py** - `0c8427a` (feat)
2. **Task 2: Add StaticFiles media mount and write comprehensive tests** - `0856eec` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `workspace/sci_fi_dashboard/chat_pipeline.py` - IMAGE branch replaced: enabled check, Vault block, `_generate_and_send_image` helper, BackgroundTask dispatch, immediate ack return
- `workspace/sci_fi_dashboard/api_gateway.py` - `/media/image_gen_outbound` StaticFiles mount added after tts_outbound mount
- `workspace/tests/test_image_gen.py` - 577 lines, 10 tests covering all three requirements (IMG-01, IMG-04, IMG-05)

## Decisions Made

- **Vault block placement:** The IMAGE branch contains a `session_mode == "spicy"` check that returns `role=image_blocked`. In practice, spicy sessions are caught at the outer vault routing block (line 622) BEFORE reaching IMAGE classification. The IMAGE branch Vault block is defense-in-depth for future code paths. Tests verify behavioral truth: no image BackgroundTask ever fires for spicy sessions.
- **asyncio.to_thread() for save_media_buffer:** The media store uses synchronous file I/O (os.open, os.replace, os.chmod, directory scan). Wrapping in `asyncio.to_thread()` prevents event loop blocking on slow disks.
- **channel_id="whatsapp" hardcoded:** `persona_chat()` does not receive a channel identifier — matches the identical hardcode in `continue_conversation()` in `pipeline_helpers.py:151`.
- **Test stub approach:** Stubbing `sci_fi_dashboard._deps` at `sys.modules` level before import breaks the circular import chain (`chat_pipeline` → `_deps` → `chat_pipeline`) and avoids pyarrow, lancedb, flashrank, torch being required in the test environment.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug/Discovery] Vault block behavior clarification**
- **Found during:** Task 2 (writing test_image_request_vault_blocked)
- **Issue:** The plan's test expected `role=image_blocked` for spicy sessions, but spicy sessions are caught at line 622 (outer vault routing) BEFORE reaching the IMAGE branch. The IMAGE branch Vault block is defense-in-depth but is not exercised via the normal spicy session path.
- **Fix:** Updated `test_image_request_vault_blocked` to verify the actual behavioral truth: spicy sessions never dispatch an image BackgroundTask. Added clear docstring explaining both code paths. The IMAGE branch Vault block remains as defense-in-depth.
- **Files modified:** workspace/tests/test_image_gen.py
- **Verification:** Test passes; no BackgroundTask.add_task called for spicy sessions
- **Committed in:** `0856eec` (Task 2 commit)

---

**Total deviations:** 1 auto-discovered (test design clarification, no production code change)
**Impact on plan:** Behavioral safety requirement is met (no image gen API calls in spicy sessions). Test accurately documents the actual code architecture.

## Issues Encountered

- `chat_pipeline.py` → `_deps.py` circular import required sys.modules stubbing strategy before import
- `deps.dual_cognition.trajectory.get_summary()` returns MagicMock which fails `"\n\n".join()` — fixed by setting `trajectory=None` in mock
- `STRATEGY_TO_ROLE` maps `"acknowledge"` (CognitiveMerge default) to "CASUAL", bypassing route_traffic_cop — fixed by patching `STRATEGY_TO_ROLE={}` in pipeline routing tests

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 9 complete: all three plans (01-engine, 02-classification, 03-integration) done
- IMG-01, IMG-02, IMG-03, IMG-04, IMG-05 all satisfied
- Phase 10 (CRON + DASH) can proceed: IMAGE role + TTS role are both live in the pipeline, enabling dashboard SSE events for both

---
*Phase: 09-image-generation*
*Completed: 2026-04-09*

## Self-Check: PASSED

- FOUND: workspace/sci_fi_dashboard/chat_pipeline.py
- FOUND: workspace/sci_fi_dashboard/api_gateway.py
- FOUND: workspace/tests/test_image_gen.py
- FOUND: .planning/phases/09-image-generation/09-03-SUMMARY.md
- FOUND: commit 0c8427a (Task 1 — IMAGE BackgroundTask dispatch)
- FOUND: commit 0856eec (Task 2 — StaticFiles mount + tests)
