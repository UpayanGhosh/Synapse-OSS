---
phase: 15
plan: 0
subsystem: baileys-bridge/test
tags: [tdd, wave-0, red-baseline, node-test, pytest, ogg-fixture]
dependency_graph:
  requires: []
  provides:
    - baileys-bridge/lib/creds_queue.js (Wave 0 skeleton — Wave 1 implements)
    - baileys-bridge/lib/restore.js (Wave 0 skeleton — Wave 2 implements)
    - baileys-bridge/test/*.test.js (RED baselines for Plans 01/02/05/06)
    - workspace/tests/test_bridge_auth.py (RED baselines for Plans 03/04)
    - baileys-bridge/test/fixtures/test_voice.ogg (committed synthetic fixture)
    - 15-MANUAL-VALIDATION.md (manual checklist for BAIL-02/03/04)
  affects: []
tech_stack:
  added:
    - node:test (built-in, Node 22) — test runner for bridge unit tests
  patterns:
    - Wave 0 RED-baseline TDD: stubs throw NOT_IMPLEMENTED_WAVE_1 so tests fail before impl
    - Synthetic OGG Opus fixture (hand-crafted 3-page minimal container, 129 bytes)
    - Python pytest skipif guards for live-bridge tests (WAVE_15_LIVE_BRIDGE_7X env var)
key_files:
  created:
    - baileys-bridge/package.json (test script added)
    - baileys-bridge/lib/creds_queue.js
    - baileys-bridge/lib/restore.js
    - baileys-bridge/test/helpers/tmp_auth_dir.js
    - baileys-bridge/test/helpers/corrupt_fixtures.js
    - baileys-bridge/test/creds_queue.test.js
    - baileys-bridge/test/restore.test.js
    - baileys-bridge/test/send_shapes.test.js
    - baileys-bridge/test/extract_payload.test.js
    - baileys-bridge/test/fixtures/test_voice.ogg
    - baileys-bridge/test/fixtures/README.md
    - workspace/tests/test_bridge_auth.py
    - .planning/phases/15-auth-persistence-baileys-7x/15-MANUAL-VALIDATION.md
  modified:
    - baileys-bridge/package.json (test script + Windows glob fix)
    - .planning/phases/15-auth-persistence-baileys-7x/15-VALIDATION.md (flags flipped)
decisions:
  - Used node --test test/*.test.js glob instead of test/ directory path — Windows requires explicit glob; directory path triggers MODULE_NOT_FOUND on Node 22 win32
  - ffmpeg absent; synthetic OGG Opus written via hand-crafted Node.js page builder (3 pages: BOS+OpusHead, OpusTags, EOS+silence frame) — 129 bytes, valid OggS header
  - extract_payload.test.js wraps index.js import in try/catch — index.js tries to bind :5010 at load time; file-level failure counted as 1 suite RED rather than 4 individual RED tests (Wave 0 contract satisfied: module import fails = RED)
metrics:
  duration: 7m13s
  completed: 2026-04-22
  tasks_completed: 3
  tasks_total: 3
  files_created: 13
  files_modified: 2
---

# Phase 15 Plan 0: Wave 0 Test Scaffold Summary

Node test harness, lib stubs, OGG fixture, RED Python stubs, VALIDATION.md Wave 0 gate — all committed.

## What Was Built

Wave 0 establishes the failing test baseline for every Phase 15 requirement. No production
code was changed (`baileys-bridge/index.js` is untouched). All downstream implementation
waves (Plans 01-06) have concrete RED→GREEN targets.

### Task 1: Harness + Skeletons + Fixtures

- `baileys-bridge/package.json` updated with `"test": "node --test test/*.test.js"`
- `baileys-bridge/lib/creds_queue.js` — 5 exports, all stub-throw `NOT_IMPLEMENTED_WAVE_1`
- `baileys-bridge/lib/restore.js` — 4 exports; `resolveWebCredsPath` + `resolveWebCredsBackupPath` implemented (trivial path joins); `readCredsJsonRaw` + `maybeRestoreCredsFromBackup` stub-throw
- `baileys-bridge/test/helpers/tmp_auth_dir.js` — `createTmpAuthDir()` + `cleanup(dir)`
- `baileys-bridge/test/helpers/corrupt_fixtures.js` — 4 writers: valid/corrupt creds + valid/corrupt backup
- `baileys-bridge/test/fixtures/test_voice.ogg` — 129-byte synthetic OGG Opus (3 pages, starts `OggS`, zero PII)
- `baileys-bridge/test/fixtures/README.md` — provenance documentation

### Task 2: RED Test Stubs

Node test results (15 tests, 15 fail, exit=1):

| File | Tests | Status | Requirements |
|------|-------|--------|--------------|
| creds_queue.test.js | 5 | RED (NOT_IMPLEMENTED_WAVE_1) | AUTH-V31-01, AUTH-V31-03 |
| restore.test.js | 5 | RED (NOT_IMPLEMENTED_WAVE_1) | AUTH-V31-02 |
| send_shapes.test.js | 4 | RED (missing lib/send_payload.js) | BAIL-03 |
| extract_payload.test.js | 4 | RED (index.js EADDRINUSE at load) | BAIL-04 |

Python test results (2 failed, 3 skipped):

| Test | Status | Reason |
|------|--------|--------|
| test_baileys_version_pin | FAILED | `^6.7.21` != `7.0.0-rc.9` (Plan 04 fixes) |
| test_node_engine_requirement | FAILED | `>=18.0.0` != `>=20.0.0` (Plan 04 fixes) |
| test_corruption_recovery_no_qr | SKIPPED | Plan 03 stub |
| test_qr_endpoint_returns_string | SKIPPED | WAVE_15_LIVE_BRIDGE_7X not set |
| test_group_metadata_shape | SKIPPED | WAVE_15_LIVE_BRIDGE_7X not set |

### Task 3: VALIDATION.md + MANUAL-VALIDATION.md

- `15-VALIDATION.md` frontmatter flipped: `nyquist_compliant: true`, `wave_0_complete: true`, `status: approved`
- Wave 0 checklist all `[x]`
- Validation Sign-Off all `[x]`, Approval: Wave 0 complete — 2026-04-22
- `15-MANUAL-VALIDATION.md` created (170 lines): BAIL-02 pairing walkthrough, BAIL-03 5-row media send matrix with exact curl commands, BAIL-04 group round-trip + sign-off table

## OGG Fixture

Path: `baileys-bridge/test/fixtures/test_voice.ogg`
Size: **129 bytes**
Header: `OggS` (bytes 0-3)
Generation: Hand-crafted Node.js OGG page builder (ffmpeg absent on this host)

## Test Exit Code

`npm test` exit code: **1** (non-zero — RED baseline confirmed)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Windows glob compatibility for node --test**

- **Found during:** Task 1 verification
- **Issue:** `node --test test/` on Windows/Node 22 attempts to load `test` as a CJS module path, producing `Cannot find module 'test'` (MODULE_NOT_FOUND). The plan spec used `test/` (directory path) which works on Linux but not Windows win32.
- **Fix:** Changed test script to `node --test test/*.test.js` (explicit glob). Shell expands glob before passing to node, which then runs each matched `.test.js` file.
- **Files modified:** `baileys-bridge/package.json`
- **Commit:** f808b34

**2. [Note] extract_payload.test.js counts as 1 suite failure, not 4 individual**

- **Observed:** `index.js` starts an Express server on port 5010 at module load time. When the test runner requires `../index.js`, the bridge tries to bind `:5010` — if the bridge is already running, this throws `EADDRINUSE` before any tests execute. The 4 individual tests are never registered; the file-level runner reports 1 failure.
- **Impact on contract:** The Wave 0 contract says "tests fail RED" — a file-level load failure is RED by definition. The 4 test stubs are correctly authored and will register properly once Plan 05 adds the `require.main !== module` guard and `module.exports = { extractPayload }` export.
- **No fix needed:** This is the intended RED state. Plan 05 resolves it.

## Wave 1 Unblock Confirmation

Plans 15-01 and 15-02 are now unblocked:

- `baileys-bridge/lib/creds_queue.js` exports the exact interface contract (`enqueueSaveCreds`, `safeSaveCreds`, `waitForCredsSaveQueueWithTimeout`, `__resetQueuesForTest`, `CREDS_SAVE_FLUSH_TIMEOUT_MS`)
- `baileys-bridge/lib/restore.js` exports the exact interface contract (`resolveWebCredsPath`, `resolveWebCredsBackupPath`, `readCredsJsonRaw`, `maybeRestoreCredsFromBackup`)
- Test files match the names in 15-VALIDATION.md Per-Task Verification Map exactly
- `npm test` command in VALIDATION.md map matches the script: `node --test test/*.test.js`

## Self-Check: PASSED

Files verified:
- `baileys-bridge/lib/creds_queue.js` FOUND
- `baileys-bridge/lib/restore.js` FOUND
- `baileys-bridge/test/helpers/tmp_auth_dir.js` FOUND
- `baileys-bridge/test/helpers/corrupt_fixtures.js` FOUND
- `baileys-bridge/test/creds_queue.test.js` FOUND
- `baileys-bridge/test/restore.test.js` FOUND
- `baileys-bridge/test/send_shapes.test.js` FOUND
- `baileys-bridge/test/extract_payload.test.js` FOUND
- `baileys-bridge/test/fixtures/test_voice.ogg` FOUND (129 bytes, OggS header)
- `workspace/tests/test_bridge_auth.py` FOUND
- `.planning/phases/15-auth-persistence-baileys-7x/15-MANUAL-VALIDATION.md` FOUND (170 lines)
- `.planning/phases/15-auth-persistence-baileys-7x/15-VALIDATION.md` — nyquist_compliant: true CONFIRMED

Commits verified:
- 8a837a6 feat(p15-w0): Node test harness + lib stubs + OGG fixture
- f808b34 test(p15-w0): RED test stubs — 15 Node + 2 Python RED baseline
- f193bb7 docs(p15-w0): populate VALIDATION.md + scaffold MANUAL-VALIDATION.md
