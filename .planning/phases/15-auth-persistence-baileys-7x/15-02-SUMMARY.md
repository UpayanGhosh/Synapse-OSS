---
phase: 15
plan: 2
subsystem: baileys-bridge/auth
tags: [auth, restore, creds, backup, wave-1]
dependency_graph:
  requires: [15-00, 15-01]
  provides: [readCredsJsonRaw, maybeRestoreCredsFromBackup]
  affects: [baileys-bridge/index.js (Plan 03 wires restore into startSocket)]
tech_stack:
  added: []
  patterns: [synchronous-boot-guard, two-json-parse-gates, size-guard-missing-semantics]
key_files:
  created: []
  modified:
    - baileys-bridge/lib/restore.js
decisions:
  - Gate 1 (corrupt creds detection) requires its own inner try/catch — the outer catch must NOT swallow the corrupt-creds case or restoration never runs
  - Port is verbatim from OpenClaw auth-store.ts:21-65 with one structural refinement: inner try/catch for Gate 1 rather than shared outer catch
  - creds_queue.js _readRaw() NOT refactored — Plan 02 success criteria marks this optional; deferred to Plan 03 if needed
metrics:
  duration: "~8 min"
  completed: "2026-04-22"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 1
---

# Phase 15 Plan 02: restore.js Implementation — AUTH-V31-02 GREEN

**One-liner:** Boot-time creds backup restoration via synchronous two-JSON-parse-gate logic, verbatim-ported from OpenClaw auth-store.ts:21-65 with inner/outer catch separation for correct corrupt-creds detection.

## What Was Built

Replaced the two `NOT_IMPLEMENTED_WAVE_1` stubs in `baileys-bridge/lib/restore.js` with:

- **`readCredsJsonRaw(filePath)`** — synchronous raw reader with existence check + `stats.size <= 1` guard. Returns `null` for missing, 0-byte, or 1-byte files. Returns raw UTF-8 string otherwise.
- **`maybeRestoreCredsFromBackup(authDir)`** — synchronous boot-time restoration. Two JSON.parse gates protect against (1) skipping restore when creds are valid, and (2) never copying a corrupt backup. Outer try/catch swallows all errors for safe boot-time fail-through.

Port provenance: verbatim from `D:/Shorty/openclaw/extensions/whatsapp/src/auth-store.ts:21-65`.

Final `lib/restore.js` line count: **64 lines** (plan required >= 55).

## Test Results

```
node --test test/restore.test.js
# tests 5
# pass 5
# fail 0
```

Full suite (all Wave 0 + Wave 1 complete plans):
```
node --test test/*.test.js
# tests 18
# pass 10   (5 creds_queue from Plan 01 + 5 restore from this plan)
# fail 8    (Wave 1 stubs for Plans 03-05, not yet implemented)
```

AUTH-V31-02 is now GREEN at unit level. Integration pending Plan 03 (wiring into `index.js::startSocket`).

## Deviation from Plan

### Auto-fixed: Inner try/catch required for Gate 1

**Found during:** Test run (Test 1 failing — corrupt creds not restored)

**Issue:** The initial implementation put Gate 1's `JSON.parse(raw)` inside the outer `try/catch`. When creds.json was corrupt, `JSON.parse` threw, was caught by the outer catch, and the function returned silently — treating corrupt creds identically to "no error" rather than falling through to backup restoration.

**Root cause:** OpenClaw's TypeScript source uses `async/await` with a distinct control flow. The CommonJS synchronous port requires the Gate 1 parse to be in an inner try/catch so that a parse failure is handled locally (fall through to restore), not swallowed by the outer catch (which must only handle catastrophic I/O errors).

**Fix:** Wrapped Gate 1 in an inner try/catch:
```javascript
if (raw) {
  try { JSON.parse(raw); return; } catch { /* corrupt — fall through to restore */ }
}
```

**Files modified:** `baileys-bridge/lib/restore.js`

**Commit:** 0287b73

This is a correctness refinement, not algorithmic drift — the behavior matches OpenClaw's TypeScript semantics exactly.

## creds_queue.js Refactor

**Decision: No** — `creds_queue.js` retains its local `_readRaw()` helper (introduced in Plan 01 to avoid a forward dependency on this plan). Plan 02 success criteria marks this refactor as optional. The duplication is 10 lines; deferred to Plan 03 if the opportunity arises during wiring.

## Threat Model Coverage

| Threat ID | Disposition | Status |
|-----------|-------------|--------|
| T-15-02b | mitigate | DONE — two JSON.parse gates implemented; corrupt backup never copied |
| T-15-07 | mitigate | DONE — `stats.size <= 1` guard rejects 0-byte and 1-byte files |
| T-15-08 | accept | No change needed |
| T-15-09 | accept | `console.warn` path is local filesystem path, no PII |

## Self-Check

- `baileys-bridge/lib/restore.js` exists and is 64 lines
- Commit 0287b73 present in git log
- `maybeRestoreCredsFromBackup` is synchronous (no `async`, no `await`, no Promise)
- Two `JSON.parse` calls present: one in inner Gate 1 catch, one on backup before `copyFileSync`
- `stats.size <= 1` guard present verbatim
- Outer `try/catch` with empty catch body swallows all I/O errors

## Self-Check: PASSED
